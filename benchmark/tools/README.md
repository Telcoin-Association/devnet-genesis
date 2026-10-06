# benchmark/tools

## Latency probe

`latency-probe.sh` measures round-trip time between GCP zones over a VPC's internal addresses, and
`latency-matrix.py` turns one run into tables. They feed one question: how fast can consensus run
when the validators sit in these zones? Consensus traffic rides QUIC over UDP, so the UDP echo RTT is
the headline number; TCP connect time and ICMP ping are measured alongside for comparison.

### What a run does

1. **Preflight.** Refuses to start if any `lat-*` instance labelled `purpose=latency-probe`, or the
   firewall rule `latency-probe-allow` / `latency-probe-allow-iap`, already exists in the project.
2. **Firewall.** Two temporary ingress rules on the VPC, both targeting the network tag
   `latency-probe`: `latency-probe-allow` (icmp, tcp:7777, udp:7778 from the same tag) and
   `latency-probe-allow-iap` (tcp:22 from the IAP range 35.235.240.0/20).
3. **VMs.** One VM per zone, `lat-<zone>`: Debian 12, no external IP, no service account, tag
   `latency-probe`, label `purpose=latency-probe`. Created up to 8 at a time. If a zone is out of the
   machine type (stockout, unavailable), the probe retries once with `e2-micro`; if that fails too the
   zone is recorded as skipped and the run continues.
4. **SSH.** Waits for IAP SSH on every VM (up to 5 sessions at a time; one retry when IAP refuses a
   tunnel with 4003/4033/4047).
5. **Echo servers.** Starts a python3 TCP echo server on 7777 and a UDP echo server on 7778 on every
   VM. Nothing is installed; Debian 12 ships python3 and ping.
6. **Measure.** On every VM (up to 5 at a time), one script probes every peer's internal IP. All
   peers are probed at once, one kind at a time:
   - ICMP: `ping -c <pings> -i 0.25`; min/avg/max/mdev and loss from ping's summary.
   - UDP: `<udp-count>` echoes of a `<udp-size>`-byte payload at 4/s per peer, each with a 2 s
     timeout. Per-sample RTT, median, p95 (nearest rank), loss %.
   - TCP: `<tcp-count>` non-blocking connects at 4/s per peer, 2 s timeout. A connect completes
     after one round trip (SYN, SYN-ACK). Per-sample RTT, median, p95.
   The script prints one JSON object, saved as `<out>/<zone>.json`.
7. **run.json** records the argv, the zone list, skipped and failed zones, each VM's machine type
   and internal IP, and the timestamps. The VM logs (gcloud stderr, remote output) stay in
   `<out>/logs/`.
8. **Cleanup** (see below), then exit. The exit status is non-zero when a zone that was not skipped
   produced no JSON, or when cleanup left something behind.

A run over 18 zones takes about 9 minutes end to end: 1 to create, 2 for SSH and the echo servers,
2 to measure, 4 to delete.

### Flags

| flag | default | meaning |
|---|---|---|
| `--project <id>` | required | GCP project |
| `--zones <list>` / `--zones @file` | required | comma list, or a file with one zone per line (`#` comments). Duplicates are dropped. |
| `--network <vpc>` | `default` | VPC the VMs attach to and the firewall rules live in |
| `--subnet <name>` | none | needed for a custom-mode VPC; the same subnet name must exist in every probed region |
| `--machine-type <type>` | `e2-small` | probe VM type; on a stockout, one retry with `e2-micro` |
| `--out <dir>` | see below | output directory; must be empty or absent |
| `--pings <n>` | 40 | ICMP echoes per pair (10 s at 4/s) |
| `--udp-count <n>` | 40 | UDP echoes per pair |
| `--udp-size <bytes>` | 1200 | UDP payload, 16 to 1432 (1432 = 1460-byte GCP MTU minus IP and UDP headers). 1200 is a typical QUIC datagram. |
| `--tcp-count <n>` | 20 | TCP connects per pair |
| `--dry-run` | | print every gcloud argv and both remote scripts; create nothing, call nothing |
| `--keep` | | skip cleanup and print the delete commands instead (for debugging a VM) |

The default `--out` is `benchmark/results/latency/<UTC stamp>` when the probe runs from the repo root
(that directory is gitignored), else `./latency-<UTC stamp>`. The probe does not read
`benchmark/config.sh` or `BENCH_RUN_ID`; it needs bash (3.2 is enough), perl, python3 and an
authenticated gcloud.

### Examples

```bash
# Rehearse with two zones first, end to end, including cleanup.
benchmark/tools/latency-probe.sh --project my-project --zones us-west2-a,europe-west2-b

# Another project and VPC, a zone file, a smaller VM.
benchmark/tools/latency-probe.sh --project other-project --network lab-vpc \
    --zones @zones.txt --machine-type e2-micro --out /tmp/lat-lab

# Tables, plus a nearest-validator table per committee layout (a zone repeats once per validator).
benchmark/tools/latency-matrix.py benchmark/results/latency/<stamp> \
    --layout paired=us-west2-a,us-west2-a,europe-west2-b,europe-west2-b,asia-northeast1-b,asia-northeast1-b \
    --layout spread=us-west2-a,europe-west2-b,asia-northeast1-b,australia-southeast1-c,asia-south1-a

# Re-cut the same raw data for a subset of zones.
benchmark/tools/latency-matrix.py benchmark/results/latency/<stamp> --out /tmp/cut \
    --zones us-west2-a,europe-west2-b,asia-northeast1-b
```

### Output tables (latency-matrix.py)

`latency-matrix.py <raw dir> [--out DIR] [--zones a,b,...|@file] [--layout name=z1,z2,...]...`
writes into `--out` (default: the raw directory). Every RTT is in milliseconds. A matrix cell
averages the two directions (a to b, b to a) when both were measured; `*` marks a cell with one
direction only, and `—` means no data (not measured, or every probe lost). Skipped zones are left out
of the tables and named in the header.

- `matrix-udp.csv` / `.md`: zone by zone, median UDP echo RTT. The number to plan with.
- `matrix-tcp.csv` / `.md`: median TCP connect RTT.
- `matrix-icmp.csv` / `.md`: ping average RTT.
- `tcp-vs-udp.md`: one row per zone pair with the UDP median (and each direction's), the TCP median
  and its min–max over both directions, the delta (ms and % of TCP) and the worse direction's UDP
  loss. A pair is flagged when UDP is more than 10 % slower than TCP or when any UDP echo was lost.
  A flag on a pair with a wide TCP range usually means the UDP flow sits on a slower ECMP path (see
  Known limits), not that the network treats UDP differently.
- `kth-nearest.md`: for each zone, the other zones ordered by UDP RTT, with the 5th and 6th nearest
  called out. With 10 validators (f = 3) a quorum is 7 votes: a validator's own plus 6 from peers,
  so the 6th-nearest peer bounds how long a vote round takes from that validator.
- `kth-nearest-<name>.md` (one per `--layout`): the same per distinct zone of a validator layout,
  where a zone may hold several validators. Two validators in one zone are 1 ms apart unless an
  intra-zone RTT was measured (the probe runs one VM per zone, so it never is); such entries carry
  `†`. The footer gives the slowest validator's 6th-nearest RTT, which is the vote-quorum floor for
  the whole committee.
- `summary.json`: all of the above in machine-readable form (matrices, pairs and flags, widest
  pairs, kth-nearest, layouts, zone list, skipped and failed zones). Project ids and IP addresses are
  scrubbed from error text, so the tables can be committed (see `benchmark/latency/`).

### Cleanup guarantees

A trap on EXIT, INT and TERM deletes every instance labelled `purpose=latency-probe` whose name starts
with `lat-` and both firewall rules, then lists again and exits 3 if anything is still there. It
finds the VMs by label, not by what the run thinks it created, so a VM whose create call timed out
is still found. When the run was interrupted while VMs were being created, it sweeps a second time
after 30 s, because a create that the client gave up on can still land. With `--keep` nothing is
deleted and the delete commands are printed. To check by hand:

```bash
gcloud compute instances list --project=<p> --filter='labels.purpose=latency-probe'
gcloud compute firewall-rules list --project=<p> --filter='name~^latency-probe'
```

### Cost

Small. 18 `e2-small` VMs with 10 GB standard boot disks for about 10 minutes cost a few cents,
and the probe traffic (about 100 KB per pair) is negligible against inter-region egress pricing.

### Known limits

- The probe VMs are shared-core `e2-small` machines; the validators run on `c3-highcpu-8`. A
  shared-core VM adds scheduling jitter (worst in p95 and in the ICMP max), and C3 networking can
  shave a little off intra-region RTT. Inter-region RTT is dominated by distance and routing, so
  the medians carry over; the tails are an upper bound.
- UDP is a raw echo of one datagram, not a QUIC connection: no handshake, no congestion control,
  no encryption, no stream multiplexing. It measures the network path a QUIC packet takes, not
  QUIC's own overhead.
- TCP connect timing is one SYN/SYN-ACK round trip measured in user space on the client; it says
  nothing about throughput.
- The UDP probe uses one socket per peer, so every echo to that peer shares one 5-tuple and one
  ECMP path, as a QUIC connection does. Each TCP connect uses a fresh source port and can land on a
  different path, so TCP samples spread wider. The two directions of a pair are separate flows and
  can land on different paths too: on 2026-10-06 australia-southeast1-c to europe-west2-b was 301 ms
  one way and 327 ms the other, with TCP connects at about 275, 301 and 327 ms. A matrix cell
  averages the two directions; `tcp-vs-udp.md` and `summary.json` keep both.
- The UDP echo server is a python3 loop, so a UDP sample includes its turnaround (about 0.1 ms on
  `e2-small`), while a TCP connect completes in the peer's kernel. Below 1 ms RTT this makes UDP look
  slower than TCP; above a few ms it is noise.
- Within one VM all peers are probed at once. The load is tiny (4 packets/s per peer), but on a
  shared-core VM the measuring process can still be descheduled for a moment, which shows up as
  an outlier sample rather than a shifted median.
- One VM per zone: intra-zone RTT is not measured.
- Internal IPs only. Traffic between public IPs can take a different path.
