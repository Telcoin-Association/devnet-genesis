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

## params-apply

`params-apply.sh` changes consensus parameters (`max_header_delay`, `min_header_delay`,
`vote_timeout`, ...) on a running fleet, between the arms of a parameter sweep. It restarts one node
at a time, waits until that node is back in consensus before it touches the next, and records each
arm so the report can tell which values ran when. Deploy step 9's `BENCH_NODE_PARAM_OVERRIDES` sets
values at deploy time; this tool changes them afterwards.

```
params-apply.sh (--nodes <file> | --from-config) --set <all|node>:<key>=<value>[,...] [--set ...] --arm <name>
params-apply.sh (--nodes <file> | --from-config) --stage-test <node> [--set ...]
params-apply.sh (--nodes <file> | --from-config) --close-arm <name>
```

`--help` lists every option. `--dry-run` prints every gcloud command and every remote script and
contacts nothing.

### What a run does

1. **Phase A, read-only.** One IAP SSH session per node, up to five at once. Each reads where the
   node's `parameters.yaml` is, its content and SHA-256, whether the `telcoin` container runs, and
   the chain id on `127.0.0.1:8545`. The file sits in the host side of the wrapper's
   `-v <host>:<datadir>` bind for `--datadir` in `/opt/telcoin/start-telcoin.sh` (deploy step 9's
   rule), or in the nodes file's `hostdatadir`. If any node fails here, nothing is changed.
2. **Validation, local.** Each node's resulting values (its current file plus the `--set` values)
   must pass the rules the node checks at startup: `min_header_delay <= max_header_delay`;
   `1 <= header_num_of_batches_threshold <= max_header_num_of_batches`; `vote_timeout` (5 s when
   absent) at least `max_header_delay + 250 ms` and below 10 s. `gc_depth` and `basefee_address` are
   refused (fleet-wide), and so are keys the file holds as a `secs`/`nanos` block. What `--set`
   alone gets wrong is refused before any node is contacted. Then the plan prints, per node,
   `key old -> new`.
3. **Phase B, serial.** Only nodes whose values change, observers first. Per node, in one session:
   save the container log as `/var/lib/bench-logs/telcoin-pre-arm-<arm>-<UTC>.log.gz` (a restart
   drops it; the harness pull collects that directory), copy the file to
   `parameters.yaml.bak-<UTC>`, rewrite each key in place as `key: value  # bench-override`,
   `systemctl restart telcoin`, then wait up to 180 s for the node to come back (see PARAMS_OK
   below). The file is rewritten through `cat >`, so owner, mode and inode stay. A file without
   `# bench-override` lines is first copied to `parameters.yaml.bak`, the copy a later deploy step 9
   restores from. Phase B also refuses a file whose SHA-256 changed since phase A.

Arms are cumulative: each one starts from the node's current file, so a key an arm does not set
keeps the value the last arm gave it.

The first node that does not come back stops the run with a non-zero exit. The tool prints why, the
`gcloud compute ssh <node> --zone=<zone> --project=<project> --tunnel-through-iap` command to
inspect it, and the `cp -p parameters.yaml.bak-<UTC> parameters.yaml && systemctl restart telcoin`
rollback. Nodes after it are untouched.

### Nodes file

One node per line: `name zone project role [hostdatadir]`. Role is `validator` or `observer`.
Project `-` takes `--project`. `hostdatadir` is the host directory that holds `parameters.yaml`;
leave it out and the wrapper decides. `#` starts a comment. The devnet, by hand:

```
# name               zone                        project     role
validator-1-devnet   us-west2-a                  tn-devnet   validator
validator-2-devnet   australia-southeast1-c      tn-devnet   validator
validator-3-devnet   northamerica-northeast1-b   tn-devnet   validator
validator-4-devnet   europe-west4-a              tn-devnet   validator
observer-5-devnet    europe-west2-b              tn-devnet   observer
```

On a four-validator committee one node down leaves no fault margin; make sure the other three are
in consensus before an arm starts.

`--from-config` reads the bench fleet from `benchmark/config.sh` (it needs `BENCH_RUN_ID`), writes
it to `results/<run>/nodes.txt`, and records into `results/<run>/manifest.json`. With `--nodes`,
nothing from the devnet or bench config is loaded. `--validators-only` leaves observers out;
otherwise `all:` reaches them too.

### Stage test first

On a fleet's first use, before the first arm:

```
BENCH_RUN_ID=<run> benchmark/tools/params-apply.sh --from-config --stage-test bench-observer-11
```

It runs phase A and phase B on that one node with no value change: the keys `--set` names (by
default the two header delays) are written back with their current values, then the node restarts
and has to come back. The saved log is `telcoin-stage-test-<UTC>.log.gz`. No arm is recorded. It
shows that the datadir lookup, the log save, the rewrite, the restart and the health wait all work
on that fleet's nodes before an arm depends on them.

### PARAMS_OK

```
PARAMS_OK <node> max=<ms> min=<ms> batch=<ms> thr=<n> vote=<ms|->
```

One line per restarted node, printed only once all of these hold:

- `eth_chainId` answers on `127.0.0.1:8545`, with the chain id the node had in phase A;
- the node's consensus moved past where it was before the restart. A validator needs a
  `quorum reached` or `header proposed` line whose (epoch, round) is above the highest one in the
  last 20000 lines before the restart. An observer needs a consensus number (`consensus_number=`,
  `got new consensus <n>/`, `last_consensus_height=`) above the one it had. Block height is no
  measure: an idle chain stays at block 0;
- the boot lines since the restart (`Max header delay set to <n> ms` and the min header delay, max
  batch delay and vote timeout lines) show the file's values, which proves the node reads the file
  that was rewritten. A missing boot line is noted, not fatal;
- the file read back gives the planned values. `max`, `min`, `batch` and `vote` are in ms, `thr` is
  `header_num_of_batches_threshold`, and `-` means the file does not have the key (the node's
  default applies).

### Recording

With `<results-dir>/manifest.json` present (`--results-dir`, or `results/<run>` with
`--from-config`), each arm goes into `manifest.param_arms`. Otherwise it goes into
`param-arms.json` beside the nodes file, as `{"param_arms": [...]}`.

```json
{"name": "a1", "begin": "2026-10-06T14:00:05Z", "end": null,
 "nodes": {"bench-validator-01": {"max_header_delay": "600ms", "min_header_delay": "300ms"}}}
```

- `begin` is the first restart of the arm, by the node's clock (the clock its log uses).
- `end` stays `null` until the next arm begins, which sets it to that arm's `begin`, or until
  `--close-arm <name>` sets it to now.
- `nodes` holds every node the arm's values reach, with values as written. A node that already had
  them is included even though it was not restarted.
- `failed: <node>` appears when the run stopped at that node.

An arm name is `[a-z0-9-]` and unique in the record. `report/provenance.py` accepts a logged value
when it is the fleet value, the node's step-9 override, or a value an arm begun by then set for
that node. `report/make_bundle.py` publishes the arms as rows in `consensus.param_arms`.
