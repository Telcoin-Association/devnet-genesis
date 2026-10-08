#!/usr/bin/env bash
# latency-probe.sh — measure inter-zone round-trip times on GCP: ICMP ping, TCP connect, UDP echo.
#
# One throwaway VM per zone (Debian 12, reached over IAP), temporary firewall rules, a python3 echo
# server on every VM, then every VM probes every other VM's internal IP (--addresses internal, the
# default), its external IP (external), or both side by side (both, or --external). In internal mode
# the VMs get no external IP. In external/both mode each VM gets an ephemeral Premium-tier external
# IP, as the bench nodes do (common/create-instances.sh), and a third firewall rule admits the probe
# VMs' external /32s: a packet sent to an external IP arrives from the sender's external IP, which
# the source-tag rule does not match. Each VM's result lands as <out>/<zone>.json; run.json records
# the run. latency-matrix.py turns the directory into tables. Everything the probe creates is deleted
# on exit (EXIT/INT/TERM trap) unless --keep is given.
#
# UDP is the headline number (consensus traffic rides QUIC over UDP); TCP connect and ICMP are for
# comparison. Inside one VM every target (each peer's internal and/or external IP) is probed
# concurrently, one probe kind at a time (ping, then UDP, then TCP), so a 17-peer VM finishes in about
# half a minute and a pair's internal and external numbers are taken under the same conditions.
#
# Usage: latency-probe.sh --project <id> --zones <a,b,c | @file> [options]   (--help for the list)
# Docs:  benchmark/tools/README.md, section "Latency probe".
#
# Needs: bash (3.2 is enough), perl, python3 and an authenticated gcloud on the operator machine.
set -euo pipefail

readonly NET_TAG=latency-probe
readonly LABEL_KEY=purpose
readonly LABEL_VALUE=latency-probe
readonly FW_RULE=latency-probe-allow
readonly FW_RULE_IAP=latency-probe-allow-iap
readonly FW_RULE_EXT=latency-probe-allow-ext
readonly NETWORK_TIER=PREMIUM   # the bench nodes' tier (common/create-instances.sh)
readonly IAP_RANGE=35.235.240.0/20
readonly TCP_PORT=7777
readonly UDP_PORT=7778
readonly FALLBACK_MACHINE_TYPE=e2-micro
readonly CREATE_PARALLEL=8
readonly SSH_PARALLEL=5
# A create error worth one retry on the fallback machine type: the zone is out of this family.
readonly UNAVAILABLE_RE='ZONE_RESOURCE_POOL_EXHAUSTED|stockout|does not have enough resources|resource_availability|currently unavailable|not available in|does not exist in zone|is not supported in'

usage() {
    cat <<'EOF'
Usage: latency-probe.sh --project <id> --zones <zone,zone,... | @file> [options]

Creates one Debian 12 VM per zone (IAP SSH), measures every ordered zone pair over the VPC's
internal addresses, the VMs' external addresses, or both, writes one JSON per zone plus run.json,
and deletes everything it created on exit.

Required:
  --project <id>        GCP project to run in
  --zones <list|@file>  comma list, or @file with one zone per line (# comments allowed)

Options:
  --addresses <mode>    internal (default; the VMs get no external IP), external (each VM gets an
                        ephemeral Premium-tier external IP and probes the peers' external IPs), or
                        both (internal and external targets probed side by side in one pass)
  --external            shorthand for --addresses both
  --network <vpc>       VPC to attach the VMs to (default: default)
  --subnet <name>       subnet name, needed for a custom-mode VPC (same name in every region)
  --machine-type <t>    probe VM type (default: e2-small; stockout -> one retry on e2-micro)
  --out <dir>           output directory (default: benchmark/results/latency/<UTC stamp> when run
                        from the repo root, else ./latency-<UTC stamp>)
  --pings <n>           ICMP echoes per pair, 4/s (default: 40)
  --udp-count <n>       UDP echo round trips per pair, 4/s, 2 s timeout each (default: 40)
  --udp-size <bytes>    UDP payload size, 16..1432 (default: 1200, QUIC-sized)
  --tcp-count <n>       TCP connects per pair, 4/s, 2 s timeout each (default: 20)
  --dry-run             print every gcloud argv and the remote scripts; create nothing
  --keep                skip the cleanup trap (leaves the VMs and firewall rules for debugging)
  -h, --help            this text
EOF
}

die() { echo "latency-probe: $*" >&2; exit 2; }
log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# --- arguments -------------------------------------------------------------------------
PROJECT="" NETWORK=default SUBNET="" ZONES_SPEC="" MACHINE_TYPE=e2-small OUT=""
PINGS=40 UDP_COUNT=40 UDP_SIZE=1200 TCP_COUNT=20 DRY=0 KEEP=0 ADDRESSES=internal
ORIG_ARGV=("$0" "$@")

while [ $# -gt 0 ]; do
    opt="$1" val=""
    case "${opt}" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY=1; shift; continue ;;
        --keep) KEEP=1; shift; continue ;;
        --external) ADDRESSES=both; shift; continue ;;
        --*=*) val="${opt#*=}"; opt="${opt%%=*}"; shift ;;
        --*) [ $# -ge 2 ] || die "${opt} needs a value"; val="$2"; shift 2 ;;
        *) die "unexpected argument '${opt}' (try --help)" ;;
    esac
    case "${opt}" in
        --project) PROJECT="${val}" ;;
        --addresses) ADDRESSES="${val}" ;;
        --network) NETWORK="${val}" ;;
        --subnet) SUBNET="${val}" ;;
        --zones) ZONES_SPEC="${val}" ;;
        --machine-type) MACHINE_TYPE="${val}" ;;
        --out) OUT="${val}" ;;
        --pings) PINGS="${val}" ;;
        --udp-count) UDP_COUNT="${val}" ;;
        --udp-size) UDP_SIZE="${val}" ;;
        --tcp-count) TCP_COUNT="${val}" ;;
        *) die "unknown option '${opt}' (try --help)" ;;
    esac
done

[ -n "${PROJECT}" ] || die "--project is required"
[ -n "${ZONES_SPEC}" ] || die "--zones is required"
# WANT_INT / WANT_EXT: probe the peers' internal / external IPs.
WANT_INT=1 WANT_EXT=0
case "${ADDRESSES}" in
    internal) ;;
    external) WANT_INT=0 WANT_EXT=1 ;;
    both) WANT_EXT=1 ;;
    *) die "--addresses '${ADDRESSES}' must be internal, external or both" ;;
esac
case "${PROJECT}" in *[!a-z0-9.:-]*) die "--project '${PROJECT}' is not a project id" ;; esac
for pair in "network:${NETWORK}" "machine-type:${MACHINE_TYPE}" "subnet:${SUBNET:-x}"; do
    case "${pair#*:}" in ''|*[!a-z0-9-]*) die "--${pair%%:*} '${pair#*:}' must be [a-z0-9-]" ;; esac
done
for pair in "pings:${PINGS}" "udp-count:${UDP_COUNT}" "udp-size:${UDP_SIZE}" "tcp-count:${TCP_COUNT}"; do
    case "${pair#*:}" in ''|*[!0-9]*|0*) die "--${pair%%:*} '${pair#*:}' must be a positive integer" ;; esac
done
# 1432 = the GCP default VPC MTU (1460) minus the IP and UDP headers: no fragmentation.
[ "${UDP_SIZE}" -ge 16 ] && [ "${UDP_SIZE}" -le 1432 ] || die "--udp-size must be 16..1432 bytes"

# Zones: comma/space/newline separated, or @file. Deduplicated, order kept.
ZONES=()
if [ "${ZONES_SPEC#@}" != "${ZONES_SPEC}" ]; then
    [ -r "${ZONES_SPEC#@}" ] || die "cannot read zone file '${ZONES_SPEC#@}'"
    zones_raw="$(sed 's/#.*//' "${ZONES_SPEC#@}")"
else
    zones_raw="${ZONES_SPEC}"
fi
zones_raw="$(printf '%s' "${zones_raw}" | tr ',\t\r\n' '    ')"
zone_re='^[a-z]+-[a-z]+[0-9]+-[a-z]$'
set -f
for z in ${zones_raw}; do
    [[ "${z}" =~ ${zone_re} ]] || die "'${z}' is not a zone name (like us-west2-a)"
    case " ${ZONES[*]-} " in *" ${z} "*) continue ;; esac
    ZONES+=("${z}")
done
set +f
[ "${#ZONES[@]}" -ge 2 ] || die "need at least two distinct zones (got ${#ZONES[@]})"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
if [ -z "${OUT}" ]; then
    if [ "$(pwd -P)" = "$(cd "${REPO_ROOT}" && pwd -P)" ] && [ -d benchmark ]; then
        OUT="benchmark/results/latency/${STAMP}"
    else
        OUT="./latency-${STAMP}"
    fi
fi

# --- gcloud ----------------------------------------------------------------------------
# show_argv <argv...> — one copy-pasteable line, on stderr so a caller's stdout redirect cannot hide it.
show_argv() { { printf '  +'; printf ' %q' "$@"; printf '\n'; } >&2; }

# gc <secs> <gcloud args...> — one gcloud call under an alarm, stdin closed, --project appended.
gc() {
    local secs="$1"; shift
    if [ "${DRY}" = 1 ]; then
        printf '  [alarm %ss]' "${secs}" >&2; show_argv gcloud "$@" --project="${PROJECT}"
        return 0
    fi
    perl -e 'alarm shift; exec @ARGV' "${secs}" gcloud "$@" --project="${PROJECT}" </dev/null
}

SSH_FLAGS=(--tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=20"
           --ssh-flag="-o StrictHostKeyChecking=accept-new" --ssh-flag="-o LogLevel=ERROR")

# ssh_once <secs> <inst> <zone> <stdin-file> <remote-cmd> <err-file> — one IAP SSH call.
ssh_once() {
    local secs="$1" inst="$2" zone="$3" input="$4" cmd="$5" err="$6"
    if [ "${DRY}" = 1 ]; then
        printf '  [alarm %ss, stdin < %s]' "${secs}" "${input}" >&2
        show_argv gcloud compute ssh "${inst}" --zone="${zone}" "${SSH_FLAGS[@]}" --command="${cmd}" --project="${PROJECT}"
        return 0
    fi
    perl -e 'alarm shift; exec @ARGV' "${secs}" gcloud compute ssh "${inst}" --zone="${zone}" \
        "${SSH_FLAGS[@]}" --command="${cmd}" --project="${PROJECT}" <"${input}" 2>"${err}"
}

# iap_ssh <same args as ssh_once> — plus one retry when IAP refuses the tunnel (4003/4033/4047).
iap_ssh() {
    local rc=0
    ssh_once "$@" || rc=$?
    if [ "${rc}" -ne 0 ] && grep -Eq '\[(4003|4033|4047): ' "$6" 2>/dev/null; then
        log "  $2: IAP refused the tunnel; retrying once in 10 s"
        sleep 10
        rc=0
        ssh_once "$@" || rc=$?
    fi
    return "${rc}"
}

# pool <max> <function> <items...> — run <function> <item> in the background, at most <max> at once.
# Jobs report through files in ${WORK}; a dry run goes one at a time so its output stays readable.
pool() {
    local max="$1" fn="$2" item
    shift 2
    [ "${DRY}" = 1 ] && max=1
    for item in "$@"; do
        while [ "$(jobs -pr | wc -l)" -ge "${max}" ]; do sleep 1; done
        if [ "${DRY}" = 1 ]; then "${fn}" "${item}"; else "${fn}" "${item}" & fi
    done
    wait
}

# last_error <file> — the last few non-empty lines of a log, on one line.
last_error() { { grep -v '^[[:space:]]*$' "$1" 2>/dev/null || true; } | tail -n 3 | tr '\n' ' ' | cut -c1-500; }

# Per-zone state lives in ${WORK}/<zone>.<key> files (bash 3.2 has no associative arrays):
#   .mt (machine type), .ip (internal IP), .ext (external IP, external/both mode),
#   .skipped (create error), .failed (stage + error).
zone_get() { cat "${WORK}/$1.$2" 2>/dev/null || true; }
fail_zone() { printf '%s\t%s\n' "$2" "$3" >"${WORK}/$1.failed"; log "  FAIL lat-$1 at $2: $3"; }
zone_live() { [ -s "${WORK}/$1.mt" ] && [ ! -e "${WORK}/$1.skipped" ] && [ ! -e "${WORK}/$1.failed" ]; }

# --- remote scripts (sent over stdin to `bash -s`) ---------------------------------------
echo_script() {
    printf 'TCP_PORT=%q\nUDP_PORT=%q\n' "${TCP_PORT}" "${UDP_PORT}"
    cat <<'REMOTE'
set -euo pipefail
d=/tmp/latency-probe
mkdir -p "$d"
cat >"$d/echo.py" <<'PY'
import socket
import sys
import threading

kind, port = sys.argv[1], int(sys.argv[2])
if kind == "udp":
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    s.bind(("", port))
    while True:
        try:
            data, addr = s.recvfrom(65536)
            s.sendto(data, addr)
        except OSError:
            pass


def serve(conn):
    try:
        conn.settimeout(30)
        while True:
            data = conn.recv(65536)
            if not data:
                break
            conn.sendall(data)
    except OSError:
        pass
    finally:
        conn.close()


s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("", port))
s.listen(1024)
while True:
    c, _ = s.accept()
    threading.Thread(target=serve, args=(c,), daemon=True).start()
PY
pkill -f "$d/echo.py" 2>/dev/null || true
setsid nohup python3 "$d/echo.py" tcp "$TCP_PORT" </dev/null >"$d/echo-tcp.log" 2>&1 &
setsid nohup python3 "$d/echo.py" udp "$UDP_PORT" </dev/null >"$d/echo-udp.log" 2>&1 &
python3 - "$TCP_PORT" "$UDP_PORT" <<'PY'
import socket
import sys
import time

tcp, udp = int(sys.argv[1]), int(sys.argv[2])
deadline = time.time() + 15
while True:
    try:
        c = socket.create_connection(("127.0.0.1", tcp), timeout=1)
        c.sendall(b"x")
        ok_tcp = c.recv(1) == b"x"
        c.close()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.settimeout(1)
        u.sendto(b"y", ("127.0.0.1", udp))
        ok_udp = u.recvfrom(16)[0] == b"y"
        u.close()
        if ok_tcp and ok_udp:
            break
    except OSError:
        pass
    if time.time() > deadline:
        sys.exit("echo servers did not answer on loopback within 15 s")
    time.sleep(0.2)
print("ECHO_READY")
PY
REMOTE
}

# measure_script <zone> — header with this VM's parameters and peers, then the static body.
measure_script() {
    local zone="$1" peers="" peers_ext="" p src_ip src_ext="" mt ip ext
    if [ "${DRY}" = 1 ]; then
        src_ip="IP_OF_lat-${zone}" mt="${MACHINE_TYPE}"
        if [ "${WANT_EXT}" = 1 ]; then src_ext="EXT_IP_OF_lat-${zone}"; fi
    else
        src_ip="$(zone_get "${zone}" ip)" mt="$(zone_get "${zone}" mt)"
        if [ "${WANT_EXT}" = 1 ]; then src_ext="$(zone_get "${zone}" ext)"; fi
    fi
    for p in "${ZONES[@]}"; do
        [ "${p}" = "${zone}" ] && continue
        if [ "${DRY}" = 1 ]; then
            ip="IP_OF_lat-${p}" ext="EXT_IP_OF_lat-${p}"
        elif zone_live "${p}"; then
            ip="$(zone_get "${p}" ip)" ext="$(zone_get "${p}" ext)"
        else
            continue
        fi
        if [ "${WANT_INT}" = 1 ]; then peers="${peers} ${p}=${ip}"; fi
        if [ "${WANT_EXT}" = 1 ]; then peers_ext="${peers_ext} ${p}=${ext}"; fi
    done
    printf 'export LAT_SRC_ZONE=%q LAT_SRC_IP=%q LAT_SRC_IP_EXT=%q LAT_MACHINE_TYPE=%q\n' \
        "${zone}" "${src_ip}" "${src_ext}" "${mt}"
    printf 'export LAT_PINGS=%q LAT_UDP_COUNT=%q LAT_UDP_SIZE=%q LAT_TCP_COUNT=%q\n' \
        "${PINGS}" "${UDP_COUNT}" "${UDP_SIZE}" "${TCP_COUNT}"
    printf 'export LAT_TCP_PORT=%q LAT_UDP_PORT=%q LAT_ADDRESSES=%q\n' "${TCP_PORT}" "${UDP_PORT}" "${ADDRESSES}"
    printf 'export LAT_PEERS=%q LAT_PEERS_EXT=%q\n' "${peers# }" "${peers_ext# }"
    cat <<'REMOTE'
set -euo pipefail
exec python3 - <<'PY'
# Probes every target concurrently, one probe kind at a time; prints ONE JSON object on one line.
# A target is one peer zone at one address kind (internal or external), so in both mode a pair's
# internal and external numbers come from the same seconds on the same VM.
import errno
import json
import math
import os
import re
import selectors
import socket
import statistics
import struct
import subprocess
import time
from datetime import datetime, timezone

E = os.environ
PINGS, UDP_COUNT = int(E["LAT_PINGS"]), int(E["LAT_UDP_COUNT"])
UDP_SIZE, TCP_COUNT = int(E["LAT_UDP_SIZE"]), int(E["LAT_TCP_COUNT"])
TCP_PORT, UDP_PORT = int(E["LAT_TCP_PORT"]), int(E["LAT_UDP_PORT"])
ADDRESSES = E["LAT_ADDRESSES"]
TARGETS = [((z, "internal"), ip) for z, ip in (p.split("=", 1) for p in E["LAT_PEERS"].split())]
TARGETS += [((z, "external"), ip) for z, ip in (p.split("=", 1) for p in E["LAT_PEERS_EXT"].split())]
RATE = 4.0       # probes per second per peer (UDP and TCP; ping uses -i 0.25)
TIMEOUT = 2.0    # seconds before a UDP echo or a TCP connect counts as lost


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summary(samples):
    """median and nearest-rank p95 of a list of ms values (None when empty)."""
    if not samples:
        return {"median_ms": None, "p95_ms": None}
    s = sorted(samples)
    return {"median_ms": round(statistics.median(s), 3),
            "p95_ms": round(s[max(0, math.ceil(0.95 * len(s)) - 1)], 3)}


PING_RTT = re.compile(r"= ([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+) ms")
PING_TX = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")


def icmp_phase():
    deadline = int(PINGS / 4) + 5
    procs, out = {}, {}
    for tk, ip in TARGETS:
        try:
            procs[tk] = subprocess.Popen(
                ["ping", "-n", "-q", "-c", str(PINGS), "-i", "0.25", "-W", "2", "-w", str(deadline), ip],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True)
        except OSError as e:
            out[tk] = {"min": None, "avg": None, "max": None, "mdev": None, "loss_pct": None,
                       "error": str(e)}
    for tk, p in procs.items():
        try:
            text = p.communicate(timeout=deadline + 15)[0]
        except subprocess.TimeoutExpired:
            p.kill()
            text = p.communicate()[0]
        r = {"min": None, "avg": None, "max": None, "mdev": None, "loss_pct": 100.0}
        m = PING_TX.search(text)
        if m and int(m.group(1)) > 0:
            tx, rx = int(m.group(1)), int(m.group(2))
            r["loss_pct"] = round(100.0 * (tx - rx) / tx, 2)
        else:
            r["error"] = text.strip()[-300:]
        m = PING_RTT.search(text)
        if m:
            r["min"], r["avg"], r["max"], r["mdev"] = (float(g) for g in m.groups())
        out[tk] = r
    return out


def udp_phase():
    sel = selectors.DefaultSelector()
    nonce = os.urandom(8)
    pad = b"\0" * (UDP_SIZE - 12)
    t0 = time.perf_counter() + 0.05
    st = {}
    for i, (tk, ip) in enumerate(TARGETS):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setblocking(False)
        s.connect((ip, UDP_PORT))
        st[tk] = {"sock": s, "seq": 0, "next": t0 + i / (RATE * len(TARGETS)), "sent": {}, "rtt": {},
                  "errors": 0}
        sel.register(s, selectors.EVENT_READ, tk)
    while True:
        now = time.perf_counter()
        for x in st.values():
            while x["seq"] < UDP_COUNT and now >= x["next"]:
                seq = x["seq"]
                x["sent"][seq] = time.perf_counter()
                try:
                    x["sock"].send(nonce + struct.pack("!I", seq) + pad)
                except OSError:
                    x["errors"] += 1
                x["seq"] += 1
                x["next"] += 1.0 / RATE
                now = time.perf_counter()
        pending = [x["next"] for x in st.values() if x["seq"] < UDP_COUNT]
        if pending:
            wait = min(pending) - now
        else:
            last = max(max(x["sent"].values()) for x in st.values())
            if now >= last + TIMEOUT or all(len(x["rtt"]) == UDP_COUNT for x in st.values()):
                break
            wait = last + TIMEOUT - now
        for key, _ in sel.select(timeout=max(0.0, wait)):
            x = st[key.data]
            while True:
                try:
                    data = key.fileobj.recv(65536)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    x["errors"] += 1
                    break
                t = time.perf_counter()
                if len(data) != UDP_SIZE or data[:8] != nonce:
                    continue
                seq = struct.unpack("!I", data[8:12])[0]
                sent = x["sent"].get(seq)
                if sent is not None and seq not in x["rtt"] and t - sent <= TIMEOUT:
                    x["rtt"][seq] = (t - sent) * 1000.0
    out = {}
    for tk, x in st.items():
        x["sock"].close()
        samples = [round(x["rtt"][k], 3) for k in sorted(x["rtt"])]
        r = {"samples_ms": samples}
        r.update(summary(samples))
        r.update({"loss_pct": round(100.0 * (UDP_COUNT - len(samples)) / UDP_COUNT, 2),
                  "sent": UDP_COUNT, "received": len(samples), "size_bytes": UDP_SIZE,
                  "send_errors": x["errors"]})
        out[tk] = r
    return out


def tcp_phase():
    sel = selectors.DefaultSelector()
    t0 = time.perf_counter() + 0.05
    st = {}
    for i, (tk, ip) in enumerate(TARGETS):
        st[tk] = {"ip": ip, "n": 0, "next": t0 + i / (RATE * len(TARGETS)), "rtt": [], "failed": 0,
                  "errors": {}}

    def fail(x, why):
        x["failed"] += 1
        x["errors"][why] = x["errors"].get(why, 0) + 1

    while True:
        now = time.perf_counter()
        for tk, x in st.items():
            while x["n"] < TCP_COUNT and now >= x["next"]:
                x["n"] += 1
                x["next"] += 1.0 / RATE
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setblocking(False)
                t = time.perf_counter()
                rc = s.connect_ex((x["ip"], TCP_PORT))
                if rc == 0:
                    x["rtt"].append((time.perf_counter() - t) * 1000.0)
                    s.close()
                elif rc == errno.EINPROGRESS:
                    sel.register(s, selectors.EVENT_WRITE, (tk, t))
                else:
                    fail(x, os.strerror(rc))
                    s.close()
                now = time.perf_counter()
        for key in list(sel.get_map().values()):
            tk, t = key.data
            if now - t > TIMEOUT:
                sel.unregister(key.fileobj)
                key.fileobj.close()
                fail(st[tk], "timeout")
        pending = [x["next"] for x in st.values() if x["n"] < TCP_COUNT]
        inflight = [key.data[1] + TIMEOUT for key in sel.get_map().values()]
        if not pending and not inflight:
            break
        wait = min(pending + inflight) - now
        for key, _ in sel.select(timeout=max(0.0, wait)):
            t_end = time.perf_counter()
            tk, t = key.data
            s = key.fileobj
            sel.unregister(s)
            err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err == 0:
                st[tk]["rtt"].append((t_end - t) * 1000.0)
            else:
                fail(st[tk], os.strerror(err))
            s.close()
    out = {}
    for tk, x in st.items():
        samples = [round(v, 3) for v in x["rtt"]]
        r = {"samples_ms": samples}
        r.update(summary(samples))
        r.update({"attempts": TCP_COUNT, "failed": x["failed"], "errors": x["errors"]})
        out[tk] = r
    return out


def records(kind):
    """{peer zone: {address, ip, icmp, udp, tcp}} for one address kind."""
    return {tk[0]: {"address": kind, "ip": ip, "icmp": icmp[tk], "udp": udp[tk], "tcp": tcp[tk]}
            for tk, ip in TARGETS if tk[1] == kind}


started = utc()
icmp = icmp_phase() if TARGETS else {}
udp = udp_phase() if TARGETS else {}
tcp = tcp_phase() if TARGETS else {}
doc = {
    "src_zone": E["LAT_SRC_ZONE"],
    "src_ip": E["LAT_SRC_IP"],
    "src_ip_external": E["LAT_SRC_IP_EXT"] or None,
    "addresses": ADDRESSES,
    "machine_type": E["LAT_MACHINE_TYPE"],
    "at": started,
    "finished_at": utc(),
    "params": {"pings": PINGS, "ping_interval_s": 0.25, "udp_count": UDP_COUNT, "udp_size": UDP_SIZE,
               "tcp_count": TCP_COUNT, "rate_per_s": RATE, "timeout_s": TIMEOUT,
               "tcp_port": TCP_PORT, "udp_port": UDP_PORT},
    "peers": records("internal"),
}
if ADDRESSES != "internal":
    doc["peers_external"] = records("external")
print(json.dumps(doc, separators=(",", ":")))
PY
REMOTE
}

# --- steps -------------------------------------------------------------------------------
create_vm() {
    local zone="$1" mt="$2" subnet=() addr=(--no-address)
    [ -n "${SUBNET}" ] && subnet=(--subnet="${SUBNET}")
    # external/both: an ephemeral external IP on the bench nodes' network tier.
    if [ "${WANT_EXT}" = 1 ]; then addr=(--network-tier="${NETWORK_TIER}"); fi
    gc 300 compute instances create "lat-${zone}" --zone="${zone}" --machine-type="${mt}" \
        --network="${NETWORK}" ${subnet[@]+"${subnet[@]}"} "${addr[@]}" \
        --image-family=debian-12 --image-project=debian-cloud \
        --tags="${NET_TAG}" --labels="${LABEL_KEY}=${LABEL_VALUE}" \
        --no-service-account --no-scopes
}

create_one() {
    local zone="$1" mt="${MACHINE_TYPE}" rc=0 lg="${WORK}/$1.create.log"
    if [ "${DRY}" = 1 ]; then create_vm "${zone}" "${mt}"; echo "${mt}" >"${WORK}/${zone}.mt"; return 0; fi
    create_vm "${zone}" "${mt}" >"${lg}" 2>&1 || rc=$?
    if [ "${rc}" -ne 0 ] && [ "${mt}" != "${FALLBACK_MACHINE_TYPE}" ] && grep -Eiq "${UNAVAILABLE_RE}" "${lg}"; then
        log "  lat-${zone}: ${mt} unavailable; retrying once with ${FALLBACK_MACHINE_TYPE}"
        mt="${FALLBACK_MACHINE_TYPE}" rc=0
        create_vm "${zone}" "${mt}" >>"${lg}" 2>&1 || rc=$?
    fi
    if [ "${rc}" -eq 0 ]; then
        echo "${mt}" >"${WORK}/${zone}.mt"
        log "  created lat-${zone} (${mt})"
    else
        last_error "${lg}" >"${WORK}/${zone}.skipped"
        log "  SKIP lat-${zone}: $(cat "${WORK}/${zone}.skipped")"
    fi
}

ssh_ready_one() {
    local zone="$1" try=1 err="${WORK}/$1.ssh.err"
    while :; do
        if ssh_once 60 "lat-${zone}" "${zone}" /dev/null true "${err}" >/dev/null; then
            [ "${DRY}" = 1 ] || log "  ssh ready: lat-${zone} (attempt ${try})"
            return 0
        fi
        if [ "${try}" -ge 24 ]; then fail_zone "${zone}" ssh "$(last_error "${err}")"; return 0; fi
        try=$((try + 1))
        sleep 10
    done
}

echo_one() {
    local zone="$1" script="${WORK}/echo.sh" out="${WORK}/$1.echo.out" err="${WORK}/$1.echo.err"
    if [ "${DRY}" = 1 ]; then iap_ssh 120 "lat-${zone}" "${zone}" "${script}" 'bash -s' "${err}"; return 0; fi
    if iap_ssh 120 "lat-${zone}" "${zone}" "${script}" 'bash -s' "${err}" >"${out}" && grep -q ECHO_READY "${out}"; then
        log "  echo servers up: lat-${zone}"
    else
        fail_zone "${zone}" echo "$(last_error "${err}") $(last_error "${out}")"
    fi
}

measure_one() {
    local zone="$1" script="${WORK}/$1.measure.sh" out="${WORK}/$1.measure.out" err="${WORK}/$1.measure.err"
    local secs=$((180 + PINGS / 4 + UDP_COUNT / 4 + TCP_COUNT / 4))
    measure_script "${zone}" >"${script}"
    if [ "${DRY}" = 1 ]; then iap_ssh "${secs}" "lat-${zone}" "${zone}" "${script}" 'bash -s' "${err}"; return 0; fi
    if ! iap_ssh "${secs}" "lat-${zone}" "${zone}" "${script}" 'bash -s' "${err}" >"${out}"; then
        fail_zone "${zone}" measure "$(last_error "${err}")"
        return 0
    fi
    if python3 - "${out}" "${OUT}/${zone}.json" <<'PY'
import json
import os
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8", errors="replace") as fh:
    lines = fh.read().splitlines()
for line in reversed(lines):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        doc = json.loads(line)
    except ValueError:
        continue
    if isinstance(doc, dict) and "src_zone" in doc and "peers" in doc:
        with open(dst + ".part", "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
            fh.write("\n")
        os.replace(dst + ".part", dst)
        sys.exit(0)
sys.exit(1)
PY
    then
        log "  measured from lat-${zone}"
    else
        fail_zone "${zone}" measure "no JSON object in the remote output: $(last_error "${out}") $(last_error "${err}")"
    fi
}

delete_vm() {   # <"name zone">
    local name="${1%% *}" zone="${1##* }"
    gc 300 compute instances delete "${name}" --zone="${zone}" --quiet >/dev/null 2>&1 \
        || log "  WARN could not delete ${name} (${zone})"
}

# list_probe_vms — "name zone" per lat-* instance carrying the probe label.
list_probe_vms() {
    local name zone
    gc 120 compute instances list --filter="labels.${LABEL_KEY}=${LABEL_VALUE}" \
        --format='value(name,zone.basename())' --verbosity=error | while read -r name zone; do
        case "${name}" in lat-*) echo "${name} ${zone}" ;; esac
    done
}

# list_probe_rules — the probe's firewall rules that exist.
list_probe_rules() {
    local name
    gc 120 compute firewall-rules list --format='value(name)' --verbosity=error | while read -r name; do
        case "${name}" in "${FW_RULE}"|"${FW_RULE_IAP}"|"${FW_RULE_EXT}") echo "${name}" ;; esac
    done
}

write_run_json() {   # <status>
    [ "${DRY}" = 1 ] && return 0
    [ -d "${OUT}" ] || return 0
    LP_PROJECT="${PROJECT}" LP_NETWORK="${NETWORK}" LP_SUBNET="${SUBNET}" LP_MT="${MACHINE_TYPE}" \
    LP_PINGS="${PINGS}" LP_UDP_COUNT="${UDP_COUNT}" LP_UDP_SIZE="${UDP_SIZE}" LP_TCP_COUNT="${TCP_COUNT}" \
    LP_STAMP="${STAMP}" LP_STARTED="${STARTED_AT}" LP_STATUS="$1" LP_KEEP="${KEEP}" \
    LP_ADDRESSES="${ADDRESSES}" LP_TIER="${NETWORK_TIER}" \
    python3 - "${OUT}" "${WORK}" "${ZONES[@]}" -- "${ORIG_ARGV[@]}" <<'PY' || log "  WARN run.json not written"
import json
import os
import sys
from datetime import datetime, timezone

out, work = sys.argv[1], sys.argv[2]
rest = sys.argv[3:]
zones, argv = rest[:rest.index("--")], rest[rest.index("--") + 1:]
E = os.environ


def read(zone, key):
    try:
        with open(os.path.join(work, "%s.%s" % (zone, key)), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


doc = {
    "tool": "latency-probe.sh",
    "status": E["LP_STATUS"],
    "stamp": E["LP_STAMP"],
    "started_at": E["LP_STARTED"],
    "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "argv": argv,
    "project": E["LP_PROJECT"],
    "network": E["LP_NETWORK"],
    "subnet": E["LP_SUBNET"] or None,
    "machine_type": E["LP_MT"],
    "addresses": E["LP_ADDRESSES"],
    "network_tier": None if E["LP_ADDRESSES"] == "internal" else E["LP_TIER"],
    "params": {"pings": int(E["LP_PINGS"]), "udp_count": int(E["LP_UDP_COUNT"]),
               "udp_size": int(E["LP_UDP_SIZE"]), "tcp_count": int(E["LP_TCP_COUNT"])},
    "kept_resources": E["LP_KEEP"] == "1",
    "zones": zones,
    "skipped": [{"zone": z, "error": read(z, "skipped")} for z in zones if read(z, "skipped") is not None],
    "failed": [],
    "vms": {},
    "measured": [],
}
for z in zones:
    failed = read(z, "failed")
    if failed is not None:
        stage, _, error = failed.partition("\t")
        doc["failed"].append({"zone": z, "stage": stage, "error": error})
    if read(z, "mt") is not None and read(z, "skipped") is None:
        doc["vms"][z] = {"name": "lat-" + z, "machine_type": read(z, "mt"), "internal_ip": read(z, "ip"),
                         "external_ip": read(z, "ext")}
    if os.path.exists(os.path.join(out, z + ".json")):
        doc["measured"].append(z)
with open(os.path.join(out, "run.json"), "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=1)
    fh.write("\n")
PY
    RUN_JSON_WRITTEN=1
}

# --- cleanup -------------------------------------------------------------------------------
CLEANED=0 TOUCHED=0 RUN_JSON_WRITTEN=0 WORK=""
cleanup() {
    local rc=$? pids pid found=() line left_vms left_rules name
    [ "${CLEANED}" = 1 ] && exit "${rc}"
    CLEANED=1
    set +e
    trap - INT TERM
    pids="$(jobs -p)"
    if [ -n "${pids}" ]; then
        # A job is a subshell running perl->gcloud: stop the gcloud child first, then the subshell.
        for pid in ${pids}; do pkill -TERM -P "${pid}" 2>/dev/null; kill "${pid}" 2>/dev/null; done
        wait 2>/dev/null
    fi
    if [ "${DRY}" = 1 ]; then
        echo "== cleanup (trap on EXIT/INT/TERM; skipped with --keep)"
        for z in "${ZONES[@]}"; do gc 300 compute instances delete "lat-${z}" --zone="${z}" --quiet; done
        gc 120 compute firewall-rules delete "${FW_RULE}" --quiet
        gc 120 compute firewall-rules delete "${FW_RULE_IAP}" --quiet
        if [ "${WANT_EXT}" = 1 ]; then gc 120 compute firewall-rules delete "${FW_RULE_EXT}" --quiet; fi
        [ -n "${WORK}" ] && rm -rf "${WORK}"
        exit "${rc}"
    fi
    [ "${RUN_JSON_WRITTEN}" = 1 ] || write_run_json aborted
    if [ "${TOUCHED}" != 1 ]; then exit "${rc}"; fi
    if [ "${KEEP}" = 1 ]; then
        log "--keep: probe VMs and firewall rules left in place. Delete them with:"
        list_probe_vms | while read -r name line; do
            echo "  gcloud compute instances delete ${name} --zone=${line} --project=${PROJECT} --quiet"
        done
        echo "  gcloud compute firewall-rules delete $(list_probe_rules | tr '\n' ' ')--project=${PROJECT} --quiet"
        exit "${rc}"
    fi
    log "cleanup: deleting the probe VMs and firewall rules"
    # A killed create can still land server-side: if jobs were killed, sweep twice.
    for pass in 1 2; do
        found=()
        while read -r line; do [ -n "${line}" ] && found+=("${line}"); done < <(list_probe_vms)
        [ "${#found[@]}" -gt 0 ] && pool "${CREATE_PARALLEL}" delete_vm "${found[@]}"
        { [ "${pass}" = 1 ] && [ -n "${pids}" ]; } || break
        log "  waiting 30 s for interrupted creates to settle, then sweeping again"
        sleep 30
    done
    while read -r name; do
        [ -n "${name}" ] || continue
        gc 120 compute firewall-rules delete "${name}" --quiet >/dev/null 2>&1 \
            || log "  WARN could not delete firewall rule ${name}"
    done < <(list_probe_rules)
    left_vms="$(list_probe_vms | tr '\n' ' ')"
    left_rules="$(list_probe_rules | tr '\n' ' ')"
    if [ -n "${left_vms// /}${left_rules// /}" ]; then
        log "CLEANUP INCOMPLETE — still present: ${left_vms}${left_rules}"
        [ "${rc}" -eq 0 ] && rc=3
    else
        log "cleanup: done — no lat-* VMs or ${FW_RULE}* rules left"
    fi
    exit "${rc}"
}

# --- main ----------------------------------------------------------------------------------
log "latency probe: ${#ZONES[@]} zones, project ${PROJECT}, network ${NETWORK}, ${MACHINE_TYPE}, addresses ${ADDRESSES}"
log "  zones: ${ZONES[*]}"
if [ "${DRY}" = 1 ]; then
    log "DRY RUN — nothing is created; output would go to ${OUT}"
else
    command -v gcloud >/dev/null || die "gcloud not found"
    command -v python3 >/dev/null || die "python3 not found"
    if [ -e "${OUT}" ] && [ -n "$(ls -A "${OUT}" 2>/dev/null)" ]; then die "--out ${OUT} exists and is not empty"; fi
fi

log "preflight: no earlier probe VMs or firewall rules may exist"
if [ "${DRY}" = 1 ]; then
    gc 120 compute instances list --filter="labels.${LABEL_KEY}=${LABEL_VALUE}" --format='value(name,zone.basename())' --verbosity=error
    gc 120 compute firewall-rules list --format='value(name)' --verbosity=error
else
    pre_vms="$(list_probe_vms)" || die "preflight: could not list instances"
    [ -z "${pre_vms}" ] || die "preflight: probe VMs already exist (delete them first): $(echo "${pre_vms}" | tr '\n' ' ')"
    pre_rules="$(list_probe_rules)" || die "preflight: could not list firewall rules"
    [ -z "${pre_rules}" ] || die "preflight: firewall rule(s) already exist (delete them first): $(echo "${pre_rules}" | tr '\n' ' ')"
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/latency-probe.XXXXXX")"
if [ "${DRY}" != 1 ]; then
    mkdir -p "${OUT}"
    OUT="$(cd "${OUT}" && pwd)"
    rm -rf "${WORK}"
    WORK="${OUT}/logs"
    mkdir -p "${WORK}"
fi
trap cleanup EXIT
trap 'log "interrupted"; exit 130' INT
trap 'log "terminated"; exit 143' TERM

log "firewall: ${FW_RULE} (probe<->probe icmp tcp:${TCP_PORT} udp:${UDP_PORT}), ${FW_RULE_IAP} (IAP -> tcp:22)"
if [ "${WANT_EXT}" = 1 ]; then log "  ${FW_RULE_EXT} (probe external IPs -> same ports) follows once the external IPs are known"; fi
TOUCHED=1
gc 120 compute firewall-rules create "${FW_RULE}" --network="${NETWORK}" --direction=INGRESS \
    --allow="icmp,tcp:${TCP_PORT},udp:${UDP_PORT}" --source-tags="${NET_TAG}" --target-tags="${NET_TAG}" \
    --description="temporary: latency-probe.sh deletes it on exit" >/dev/null
gc 120 compute firewall-rules create "${FW_RULE_IAP}" --network="${NETWORK}" --direction=INGRESS \
    --allow=tcp:22 --source-ranges="${IAP_RANGE}" --target-tags="${NET_TAG}" \
    --description="temporary: latency-probe.sh deletes it on exit" >/dev/null

log "create: ${#ZONES[@]} VMs, up to ${CREATE_PARALLEL} at a time"
pool "${CREATE_PARALLEL}" create_one "${ZONES[@]}"

# Addresses: the internal IP and the external (NAT) IP of every probe VM, from one JSON listing.
if [ "${DRY}" = 1 ]; then
    gc 120 compute instances list --filter="labels.${LABEL_KEY}=${LABEL_VALUE}" --format=json --verbosity=error
else
    gc 120 compute instances list --filter="labels.${LABEL_KEY}=${LABEL_VALUE}" --format=json \
        --verbosity=error >"${WORK}/instances.json"
    python3 - "${WORK}/instances.json" >"${WORK}/instances.tsv" <<'PY'
import json
import sys

# One line per instance: name, zone, internal IP, external IP ("-" when absent).
with open(sys.argv[1], encoding="utf-8") as fh:
    for inst in json.load(fh):
        nic = (inst.get("networkInterfaces") or [{}])[0]
        nat = ((nic.get("accessConfigs") or [{}])[0]).get("natIP") or "-"
        print("%s %s %s %s" % (inst.get("name") or "-", (inst.get("zone") or "-").rsplit("/", 1)[-1],
                               nic.get("networkIP") or "-", nat))
PY
    while read -r name zone ip ext; do
        case "${name}" in "lat-${zone}") ;; *) continue ;; esac
        [ -s "${WORK}/${zone}.mt" ] || continue
        case "${ip}" in *[!0-9.]*|'') ;; *) echo "${ip}" >"${WORK}/${zone}.ip" ;; esac
        case "${ext}" in *[!0-9.]*|'') ;; *) echo "${ext}" >"${WORK}/${zone}.ext" ;; esac
    done <"${WORK}/instances.tsv"
fi
LIVE=()
for z in "${ZONES[@]}"; do
    if [ "${DRY}" = 1 ]; then LIVE+=("${z}"); continue; fi
    [ -e "${WORK}/${z}.skipped" ] && continue
    if [ ! -s "${WORK}/${z}.ip" ]; then fail_zone "${z}" create "created but no internal IP listed"; continue; fi
    if [ "${WANT_EXT}" = 1 ] && [ ! -s "${WORK}/${z}.ext" ]; then
        fail_zone "${z}" create "created but no external IP listed"; continue
    fi
    LIVE+=("${z}")
done
[ "${#LIVE[@]}" -ge 2 ] || { log "fewer than two probe VMs exist; nothing to measure"; exit 1; }

if [ "${WANT_EXT}" = 1 ]; then
    # Traffic sent to an external IP arrives from the sender's external IP, so the source-tag rule
    # does not admit it. Admit exactly the probe VMs' external /32s, before anything is measured.
    sources=""
    for z in "${LIVE[@]}"; do
        if [ "${DRY}" = 1 ]; then sources="${sources},EXT_IP_OF_lat-${z}/32"; else sources="${sources},$(zone_get "${z}" ext)/32"; fi
    done
    log "firewall: ${FW_RULE_EXT} (icmp tcp:${TCP_PORT} udp:${UDP_PORT} from the ${#LIVE[@]} probe VMs' external IPs)"
    gc 120 compute firewall-rules create "${FW_RULE_EXT}" --network="${NETWORK}" --direction=INGRESS \
        --allow="icmp,tcp:${TCP_PORT},udp:${UDP_PORT}" --source-ranges="${sources#,}" --target-tags="${NET_TAG}" \
        --description="temporary: latency-probe.sh deletes it on exit" >/dev/null
fi

log "ssh: waiting for IAP SSH on ${#LIVE[@]} VMs, up to ${SSH_PARALLEL} at a time"
pool "${SSH_PARALLEL}" ssh_ready_one "${LIVE[@]}"

echo_script >"${WORK}/echo.sh"
if [ "${DRY}" = 1 ]; then
    echo "== remote script: echo servers (stdin of 'bash -s' on every VM)"
    sed 's/^/    | /' "${WORK}/echo.sh"
fi
ready=()
for z in "${LIVE[@]}"; do zone_live "${z}" && ready+=("${z}"); done
log "echo: starting TCP :${TCP_PORT} and UDP :${UDP_PORT} echo servers on ${#ready[@]} VMs"
pool "${SSH_PARALLEL}" echo_one ${ready[@]+"${ready[@]}"}

ready=()
for z in "${LIVE[@]}"; do zone_live "${z}" && ready+=("${z}"); done
[ "${#ready[@]}" -ge 2 ] || { log "fewer than two VMs have echo servers; nothing to measure"; exit 1; }
if [ "${DRY}" = 1 ]; then
    echo "== remote script: measure (stdin of 'bash -s'; shown for lat-${ready[0]}, peers differ per VM)"
    measure_script "${ready[0]}" | sed 's/^/    | /'
fi
log "measure: ${#ready[@]} VMs, up to ${SSH_PARALLEL} at a time (${PINGS} pings, ${UDP_COUNT} x ${UDP_SIZE} B UDP, ${TCP_COUNT} TCP connects per pair)"
pool "${SSH_PARALLEL}" measure_one "${ready[@]}"

if [ "${DRY}" = 1 ]; then log "DRY RUN complete"; exit 0; fi
write_run_json complete
missing=()
for z in "${ZONES[@]}"; do
    [ -e "${WORK}/${z}.skipped" ] && continue
    [ -s "${OUT}/${z}.json" ] || missing+=("${z}")
done
skipped=()
for z in "${ZONES[@]}"; do [ -e "${WORK}/${z}.skipped" ] && skipped+=("${z}"); done
log "results: ${OUT}"
[ "${#skipped[@]}" -eq 0 ] || log "  skipped (create failed): ${skipped[*]}"
if [ "${#missing[@]}" -gt 0 ]; then
    log "  NO RESULT from: ${missing[*]} (see ${WORK}/<zone>.*.err)"
    exit 1
fi
log "  all ${#ready[@]} measured zones wrote JSON; next: benchmark/tools/latency-matrix.py ${OUT}"
