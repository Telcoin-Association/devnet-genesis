# benchmark/tools

## Latency probe

`latency-probe.sh` measures round-trip time between GCP zones over a VPC's internal addresses, the
VMs' external addresses, or both in one pass (`--addresses`), and `latency-matrix.py` turns one run
into tables. They feed one question: how fast can consensus run when the validators sit in these
zones? Consensus traffic rides QUIC over UDP, so the UDP echo RTT is the headline number; TCP connect
time and ICMP ping are measured alongside for comparison. The bench nodes dial each other on their
external IPs (ephemeral, Premium tier), so `--addresses both` is the mode that shows whether the
external path between two zones differs from the internal one.

### What a run does

1. **Preflight.** Refuses to start if any `lat-*` instance labelled `purpose=latency-probe`, or the
   firewall rule `latency-probe-allow` / `latency-probe-allow-iap` / `latency-probe-allow-ext`,
   already exists in the project.
2. **Firewall.** Two temporary ingress rules on the VPC, both targeting the network tag
   `latency-probe`: `latency-probe-allow` (icmp, tcp:7777, udp:7778 from the same tag) and
   `latency-probe-allow-iap` (tcp:22 from the IAP range 35.235.240.0/20).
3. **VMs.** One VM per zone, `lat-<zone>`: Debian 12, no service account, tag `latency-probe`,
   label `purpose=latency-probe`. With `--addresses internal` (the default) the VM has no external
   IP; with `external` or `both` it gets an ephemeral external IP on the Premium network tier, as the
   bench nodes do (`common/create-instances.sh`). Created up to 8 at a time. If a zone is out of the
   machine type (stockout, unavailable), the probe retries once with `e2-micro`; if that fails too the
   zone is recorded as skipped and the run continues.
   **Addresses.** One `gcloud compute instances list --format=json` gives every VM's internal IP and
   external (NAT) IP. In `external`/`both` mode a third ingress rule, `latency-probe-allow-ext`, admits
   icmp, tcp:7777 and udp:7778 from exactly the probe VMs' external `/32`s to the `latency-probe` tag.
   It is needed because a packet sent to an external IP arrives from the sender's external IP, which
   the source-tag rule does not match. It is created as soon as the addresses are known, before any
   SSH or measurement, and the cleanup trap deletes it.
4. **SSH.** Waits for IAP SSH on every VM (up to 5 sessions at a time; one retry when IAP refuses a
   tunnel with 4003/4033/4047).
5. **Echo servers.** Starts a python3 TCP echo server on 7777 and a UDP echo server on 7778 on every
   VM. Nothing is installed; Debian 12 ships python3 and ping.
6. **Measure.** On every VM (up to 5 at a time), one script probes every peer's internal IP, external
   IP, or both. A target is one peer at one address kind; all targets are probed at once, one kind at
   a time, so in `both` mode a pair's internal and external numbers come from the same seconds on the
   same VM:
   - ICMP: `ping -c <pings> -i 0.25`; min/avg/max/mdev and loss from ping's summary.
   - UDP: `<udp-count>` echoes of a `<udp-size>`-byte payload at 4/s per peer, each with a 2 s
     timeout. Per-sample RTT, median, p95 (nearest rank), loss %.
   - TCP: `<tcp-count>` non-blocking connects at 4/s per peer, 2 s timeout. A connect completes
     after one round trip (SYN, SYN-ACK). Per-sample RTT, median, p95.
   The script prints one JSON object, saved as `<out>/<zone>.json`: `peers` holds the internal-IP
   records and `peers_external` the external-IP ones (present in `external`/`both` mode). Every record
   carries `address` (`internal` or `external`) and `ip`, the target address.
7. **run.json** records the argv, the address mode and network tier, the zone list, skipped and
   failed zones, each VM's machine type, internal IP and external IP, and the timestamps. The VM logs
   (gcloud stderr, remote output) stay in `<out>/logs/`.
8. **Cleanup** (see below), then exit. The exit status is non-zero when a zone that was not skipped
   produced no JSON, or when cleanup left something behind.

A run over 18 zones takes about 9 minutes end to end: 1 to create, 2 for SSH and the echo servers,
2 to measure, 4 to delete.

### Flags

| flag | default | meaning |
|---|---|---|
| `--project <id>` | required | GCP project |
| `--zones <list>` / `--zones @file` | required | comma list, or a file with one zone per line (`#` comments). Duplicates are dropped. |
| `--addresses <mode>` | `internal` | `internal`: no external IPs, probe internal IPs. `external`: Premium-tier ephemeral external IPs, probe those. `both`: external IPs on the VMs, probe internal and external IPs side by side. |
| `--external` | | shorthand for `--addresses both` |
| `--network <vpc>` | `default` | VPC the VMs attach to and the firewall rules live in |
| `--subnet <name>` | none | needed for a custom-mode VPC; the same subnet name must exist in every probed region |
| `--machine-type <type>` | `e2-small` | probe VM type; on a stockout, one retry with `e2-micro` |
| `--out <dir>` | see below | output directory; must be empty or absent |
| `--pings <n>` | 40 | ICMP echoes per pair (10 s at 4/s) |
| `--udp-count <n>` | 40 | UDP echoes per pair |
| `--udp-size <bytes>` | 1200 | UDP payload, 16 to 1432 (1432 = 1460-byte GCP MTU minus IP and UDP headers). 1200 is a typical QUIC datagram. |
| `--tcp-count <n>` | 20 | TCP connects per pair |
| `--dry-run` | | print every gcloud argv (including the external-source firewall rule, with placeholder addresses) and both remote scripts; create nothing, call nothing |
| `--keep` | | skip cleanup and print the delete commands instead (for debugging a VM) |

The default `--out` is `benchmark/results/latency/<UTC stamp>` when the probe runs from the repo root
(that directory is gitignored), else `./latency-<UTC stamp>`. The probe does not read
`benchmark/config.sh` or `BENCH_RUN_ID`; it needs bash (3.2 is enough), perl, python3 and an
authenticated gcloud.

### Examples

```bash
# Rehearse with two zones first, end to end, including cleanup.
benchmark/tools/latency-probe.sh --project my-project --zones us-west2-a,europe-west2-b

# Internal and external paths side by side, the external hub column against Los Angeles.
benchmark/tools/latency-probe.sh --project my-project --zones @zones.txt --addresses both
benchmark/tools/latency-matrix.py benchmark/results/latency/<stamp> --via us-west2-a

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

`latency-matrix.py <raw dir> [--out DIR] [--zones a,b,...|@file] [--layout name=z1,z2,...]... [--via ZONE]`
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

The tables above are internal-address tables. A run with external addresses adds (and an
external-only run has only these):

- `matrix-{udp,tcp,icmp}-external.csv` / `.md`: the same three matrices over external IPs.
- `kth-nearest-external.md`: nearest zones by external UDP RTT.
- `external-vs-internal.md` (`both` runs): one row per ordered pair a → b with that flow's internal
  UDP median, external UDP median, delta, ratio, each direction's UDP loss, and a `via <hub>` column:
  external RTT(a, hub) + external RTT(hub, b), from the direction-averaged external matrix, so an
  external path that detours through the hub shows as an external median close to that sum. The hub
  is `--via ZONE`, default `us-west2-a`. A row is flagged when the external median exceeds the
  internal one by more than 25 % or more than 30 ms; a flagged row whose external median is within
  10 % of the via sum is also flagged `external ≈ via <hub>`.
- `summary.json` gains `addresses` and an `external` block (matrices, kth-nearest, and in `both` runs
  `vs_internal` with every ordered pair plus `flags`).

### Cleanup guarantees

A trap on EXIT, INT and TERM deletes every instance labelled `purpose=latency-probe` whose name starts
with `lat-` and every probe firewall rule (`latency-probe-allow`, `-iap`, `-ext`), then lists again and
exits 3 if anything is still there. It
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
- External mode measures VM-to-VM traffic between Premium-tier external IPs inside Google's network,
  which is the path the bench nodes use; it says nothing about traffic from outside Google. With an
  external IP on each probe VM, the project's own ingress rules for `0.0.0.0/0` (for example a
  default-network `default-allow-ssh`) apply to it for the few minutes it exists.

## params-apply

`params-apply.sh` puts a running fleet into a benchmark arm: the node switches of
`benchmark/arms/switches.tsv` and the consensus timing parameters (`max_header_delay`,
`min_header_delay`, `vote_timeout`, ...) in each node's `parameters.yaml`. It restarts one node at a
time, reads the node's new state back from the node's own log before it touches the next, and
records each arm so the report can tell which state ran when. `BENCH_NODE_PARAM_OVERRIDES` and
`BENCH_ARM_FILE` set values at deploy time (step 7's pre-start config writes them, before the
coordinated start); this tool changes them afterwards.

```
params-apply.sh (--nodes <file> | --from-config) --arm-file <file> [--arm <name>]
params-apply.sh (--nodes <file> | --from-config) --set <all|node>:<key>=<value>[,...] [--set ...] --arm <name>
params-apply.sh (--nodes <file> | --from-config) --stage-test <node> [--set ...]
params-apply.sh (--nodes <file> | --from-config) --close-arm <name>
params-apply.sh (--nodes <file> | --from-config) --mark <label> | --end-mark <label>
```

`--help` lists every option and every `PARAMS_APPLY_*` knob. `--dry-run` prints the per-node plan
(keys to change, whether the node restarts and why, the host steps), every gcloud command and every
remote script; it contacts nothing and records nothing.

### Arms

An arm comes from an arm file or from `--set`.

- `--arm-file benchmark/arms/<name>.arm` is the full switch state (format and refusals:
  `benchmark/arms/README.md`). A switch the file does not list goes to its default. The arm's name
  is the file's `name` line unless `--arm <name>` gives another. A file that breaks the grammar is
  refused as a whole, naming the line, before any node is contacted. `--set` cannot be combined
  with it.
- `--set` changes only the keys it names, on top of what each node has, so `--set` arms are
  cumulative. A switch takes one of its `arm_values` or its default; a timing key follows the rules
  below.

The switch names, types and allowed values come from `switches.tsv` and nowhere else. A switch is
written as `key: value  # bench-override`, a boolean as a YAML boolean (`vote_queue_fix: true`). The
node writes no switch at its default, so a node's file usually has none of them, and a switch the
file leaves out is at its default. The tool compares effective values: it appends a key the file
lacks when the arm needs another value, rewrites a line in place, and writes a switch that goes
back to its default with the default (`parent_grace: 0ms  # bench-override`); it never deletes a
line. Durations compare by value, so `0s`, `0ms` and an absent `parent_grace` are the same.

Run 1's arm files are in `benchmark/arms/`, cumulative in this order: `a0-control`,
`p1-mdbx-advice`, `v-vote` (`v-vote-floor` is the same with `quorum_exec_block_starved_rounds 0`),
`pool-local`, `pipe`, `bound`, `gr150` (`gr100` instead when 150 ms misses), `a0-prime`. `final` is a
placeholder for run 2 that the orchestrator fills. Each file starts with a comment saying what the
arm adds and what it must show; every arm from `p1-mdbx-advice` on, `a0-prime` included, evicts
`mdbx.dat` at each restart.

### What a run does

1. **Phase A, read-only.** One IAP SSH session per node, up to five at once. Each reads where the
   node's `parameters.yaml` is, its content and SHA-256, whether the `telcoin` container runs, the
   chain id on `127.0.0.1:8545`, the `node switches` line the running container logged at its start
   (the first one since its `StartedAt`), and whether the v2 library (`lib/common.sh` under
   `TN_NODE_SCRIPTS_DIR`) and `systemd-run` are there. The file is `<datadir>/parameters.yaml`, and
   the first of these gives the datadir:
   - the nodes file's `hostdatadir`;
   - `DATA_DIR` in `/etc/telcoin/.node-meta` (v2 nodes; `KEY=VALUE` lines, root 0600). A
     `DATA_DIR` set more than once has no single value and fails the node, and so does a
     `hostdatadir` that is not the `DATA_DIR` there;
   - the host side of the `-v <host>:<path>` bind for `--datadir <path>` in the node's launch file
     (the rule pre-v2 deploys used; deploy step 7 itself reads only `.node-meta`):
     `/usr/local/libexec/telcoin/tn-start-docker`, or the pre-v2 wrapper
     `/opt/telcoin/start-telcoin.sh` on a node without the v2 start script.

   The tool only reads the launch file; it never edits it. Each node's phase A summary names the
   launch file found and where its datadir came from. If any node fails here, nothing is changed.
2. **Validation, local.** Each node's resulting timing values (its current file plus the `--set`
   values) must pass the rules the node checks at startup: `min_header_delay <= max_header_delay`;
   `1 <= header_num_of_batches_threshold <= max_header_num_of_batches`; `vote_timeout` (5 s when
   absent) at least `max_header_delay + 250 ms` and below 10 s. `gc_depth` and `basefee_address` are
   refused (fleet-wide), and so are keys the file holds as a `secs`/`nanos` block. What `--set`
   alone gets wrong is refused before any node is contacted. A switch the arm sets that the running
   image does not print on its `node switches` line refuses the arm before any change; the one
   optional switch, `pipelined_persist`, may be missing while the arm leaves it at its default. A
   node that restarts needs the v2 library and `systemd-run`.

   Then the plan prints, per node, `key old -> new` and whether it restarts, with the reasons:
   `params` (a key is rewritten), `live` (its running switches are not the arm's), `unread` (it has
   no `node switches` line to compare, for example a stopped container) and `host` (the arm has host
   steps). A node with none of these is not restarted.
3. **Phase B, serial, observers first.** Per node, in one session:
   1. the committee guard, v2's `tn_committee_down_guard` against the node's own RPC (see the
      safety rules below);
   2. the container log saved as `/var/lib/bench-logs/telcoin-pre-arm-<arm>-<UTC>.log.gz` (a
      restart drops it; the harness pull collects that directory);
   3. the epoch check: no stop within ±90 s of an epoch boundary;
   4. the file copied to `parameters.yaml.bak-<UTC>` and each key rewritten in place as
      `key: value  # bench-override`, through `cat >`, so owner, mode and inode stay. A file
      without `# bench-override` lines is first copied to `parameters.yaml.bak` (the unmarked
      original). A file with `# bench-override` lines but no `.bak` is refused before any restart;
      deploy step 7 leaves exactly that on a node with `BENCH_NODE_PARAM_OVERRIDES`. Phase B also
      refuses a file whose SHA-256 changed since phase A;
   5. one transient unit, `systemd-run --unit bench-arm-<arm>-<UTC>`, runs `systemctl stop telcoin`,
      the arm's host steps and `systemctl start telcoin`. Its script and output stay in
      `/var/lib/bench-logs/arm-units/<unit>.{sh,out}`;
   6. the wait until the node is back in consensus, then the readback (`PARAMS_OK` and
      `SWITCHES_OK` below).

When every node has read back, the tool prints `ARM_READY` and records `ready`.

### Safety rules

- One node is down at a time, and observers go first.
- The guard is resampled. It counts the authors of one consensus commit, and a member that is up
  can miss one, so bench 4's single sample refused 25-50 % of the time with nobody down (lessons
  2026-11-05). One refusal is a sample: up to 8 samples, 10 s apart (`PARAMS_APPLY_GUARD_TRIES`,
  `PARAMS_APPLY_GUARD_SECS`). Eight refusals in a row are a deferral: 60 s
  (`PARAMS_APPLY_GUARD_DEFER_SECS`), then 8 more samples. A second deferral stops the run without
  touching the node. A pass that came with a warning (the guard could not count the committee)
  counts as a refusal. An observer passes at once.
- No stop within ±90 s of an epoch boundary (`PARAMS_APPLY_EPOCH_MARGIN_SECS`), on either side: the
  epoch timing is v2's `tn_epoch_secs_left`, and once the next epoch runs, its duration minus the
  seconds left is the time since the boundary. The tool waits in naps of at most 15 s, at most
  600 s in all (`PARAMS_APPLY_EPOCH_WAIT_SECS`), then gives up without touching the node. After a
  wait it takes the guard again.
- Stop, host steps and start run inside one `systemd-run` unit. The session launches it and watches
  its output file, so a dropped IAP session or the session's own alarm cannot leave the node
  stopped. The unit has no `set -e`: a failed stop skips the host steps, and the start always runs.
  A unit that does not launch restores the file, and the node is not restarted.
- The first node that fails stops the run with exit 1: a guard that defers twice, an epoch wait that
  gives up, a unit that fails its stop, host steps or start, a node not back in consensus within
  180 s (`PARAMS_APPLY_HEALTH_SECS`), or a readback that does not match. The tool prints
  `PA_FAIL <node> <why>`, records `failed: <node>` on the arm when the arm had begun, and leaves the
  later nodes untouched. On stderr it says whether the node was restarted, names the unit, and
  prints the `gcloud compute ssh <node> --zone=<zone> --project=<project> --tunnel-through-iap`
  command to inspect it and, after a restart, the `cp -p parameters.yaml.bak-<UTC>
  parameters.yaml && systemctl restart telcoin` rollback.
- Every wait has a deadline and prints when it gives up: a free SSH slot, the guard (its sample
  count), the epoch wait, the unit's start (600 s, `PARAMS_APPLY_UNIT_SECS`), back in consensus, and
  the session's own alarm.
- A dry run never reaches a live call: each one sits behind a `[ "${DRY}" = 0 ] || return` guard on
  the line before it, and the record is never written. `tests/test_params_apply.py` runs every arm
  file under a fake `gcloud` that prints `REACHED` and exits 9, and asserts it is never called.

### Readback and tags

After each start the session prints the newest `node switches` line logged since the unit's stop.
That line (message `node switches`, target `node::switches`, one `key=value` per switch in the
order of `switches.tsv`) must come from this start: a line whose own time is before the stop is
stale and fails the node. Every switch of the arm must read back with the arm's value, compared
by value: the node prints durations in humantime form (`150ms`, and `0s` for zero), which match
the tsv's `150ms` and `0ms`. A switch missing from the line fails the node, unless it is optional
and the arm leaves it at its default.
With `--set`, only the switches `--set` names are compared; with timing keys alone, none are.

| tag | when |
|---|---|
| `PA_GUARD <node> sample=<n>/<max> rc=<0\|1\|2\|blind> <guard message>` | each guard sample |
| `PA_GUARD_DEFER <node> ...` | a deferral (8 refusals in a row) |
| `PA_GUARD_SUMMARY <node> samples=<n> refused=<n>` | before the stop (or the failure) |
| `PA_EPOCH_WAIT <node> ...` / `PA_EPOCH <node> secs_left=<n> since_boundary=<n> waited=<n>` | the epoch check |
| `PA_UNIT_LAUNCHED <unit> <UTC>`, `PA_UNIT <line of the unit's output>` | the stop/start unit |
| `PA_PROGRESS_AT <UTC>`, `PA_RESTART_SECS <n>` | back in consensus; seconds from the stop |
| `PA_SWITCH_LINE <line>` | the `node switches` line read back |
| `SWITCHES_OK <node> <key>=<value> ...` | the node's switches read back, in `switches.tsv` order |
| `SWITCHES_CURRENT <node> <key>=<value> ...` | a node already in the arm (not restarted): its running line |
| `PARAMS_OK <node> max=<ms> min=<ms> batch=<ms> thr=<n> vote=<ms\|->` | the timing readback of a restarted node |
| `PARAMS_CURRENT <node> ...` | the same for a node not restarted (nothing-to-change arms) |
| `PA_FAIL <node> <why>` | the node that stopped the run |
| `ARM_READY <arm> ready=<UTC> restarted=<n> nodes=<n>` | every node is in the arm |

The `PA_*` lines from the node come indented in the run's output; the tool's own tags start the
line. `PARAMS_OK` is printed only once all of these hold:

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
  default applies);
- the switches read back (`SWITCHES_OK`), when the arm has any.

### Nodes file

One node per line: `name zone project role [hostdatadir]`. Role is `validator` or `observer`.
Project `-` takes `--project`. `hostdatadir` is the host directory that holds `parameters.yaml`;
leave it out and the node's `.node-meta` or launch file decides (phase A above). `#` starts a comment. The devnet, by hand:

```
# name               zone                        project     role
validator-1-devnet   us-west2-a                  tn-devnet   validator
validator-2-devnet   australia-southeast1-c      tn-devnet   validator
validator-3-devnet   northamerica-northeast1-b   tn-devnet   validator
validator-4-devnet   europe-west4-a              tn-devnet   validator
observer-5-devnet    europe-west2-b              tn-devnet   observer
```

On a four-validator committee one node down leaves no fault margin; the guard then needs every
other member in the counted commit, and resamples until it sees them.

`--from-config` reads the bench fleet from `benchmark/config.sh` (it needs `BENCH_RUN_ID`), writes
it to `results/<run>/nodes.txt` with every node's `hostdatadir` set to the config's
`VALIDATOR_DATA_DIR`, takes the v2 library's directory from `TN_NODE_SCRIPTS_DIR` and the guard's
public fallback RPC from `BENCH_GUARD_PUBLIC_RPC`, and records into `results/<run>/manifest.json`.
With `--nodes`, nothing from the devnet or bench config is loaded (the library defaults to
`/opt/telcoin-node-scripts`, the fallback RPC to a dead local port). `--validators-only` leaves
observers out; otherwise `all:` and an arm file reach them too.

### Stage test first

On a fleet's first use, before the first arm:

```
BENCH_RUN_ID=<run> benchmark/tools/params-apply.sh --from-config --stage-test bench-observer-11
```

It runs phase A and phase B on that one node with no value change: the keys `--set` names (by
default the two header delays) are written back with their current values, then the node stops
and starts in its unit and has to come back. The saved log is `telcoin-stage-test-<UTC>.log.gz`
and the unit `bench-arm-stage-test-<UTC>`. No arm is recorded. It shows that the datadir lookup,
the guard, the epoch check, the log save, the rewrite, the unit and the health wait all work on
that fleet's nodes before an arm depends on them. When the node logs a `node switches` line, it
must match the file; an image without the line is noted.

### Recording

With `<results-dir>/manifest.json` present (`--results-dir`, or `results/<run>` with
`--from-config`), each arm goes into `manifest.param_arms`. Otherwise it goes into
`param-arms.json` beside the nodes file, as `{"param_arms": [...]}`. The fields are frozen in
`benchmark/arms/MANIFEST-FIELDS.md`:

```json
{"name": "p1-mdbx-advice", "begin": "2026-11-12T03:10:05Z", "end": null, "via": "params-apply",
 "file": "benchmark/arms/p1-mdbx-advice.arm", "sha256": "<64 hex>",
 "switches": {"quorum_exec_block": "false", "...": "...", "mdbx_random_advice": "true", "...": "..."},
 "nodes": {"bench-observer-11": {"mdbx_random_advice": "true"}},
 "host": [{"step": "evict-mdbx", "value": null,
           "nodes": {"bench-observer-11": {"resident_pages_before": 812345, "resident_pages_after": 0}}}],
 "restart_secs": {"bench-observer-11": 41.0}, "guard": {"bench-observer-11": {"samples": 1, "refused": 0}},
 "marks": [], "ready": "2026-11-12T03:19:41Z"}
```

- `begin` is the arm's first stop, by the node's clock (the clock its log uses). The arm is opened
  there, which closes the arm open before it (`end` = this `begin`) and that arm's open marks.
- `end` stays `null` until the next arm begins or `--close-arm <name>` sets it to now.
- `via` is `params-apply`. `file` is the arm file, repo-relative (absolute for a file outside the
  repository), or `null` for an arm given with `--set`. `sha256` and `switches` (every row of
  `switches.tsv`, defaults included, values as strings) come with an arm file only.
- `nodes` holds, for an arm file, the keys rewritten on each restarted node (`{}` for a node
  restarted with nothing to rewrite). For `--set`, as before: every node the values reach, with the
  values as written, including a node that already had them and was not restarted.
- `host` lists the host steps per node, `restart_secs` the seconds from the stop to consensus
  progress, `guard` the samples taken before the node's stop and how many refused.
- `ready` is the last node's consensus progress plus 120 s (`PARAMS_APPLY_SETTLE_SECS`); an arm's
  measurement window is `ready` to `end`. `ARM_READY` prints it as soon as the last node read back,
  so it can be up to 120 s ahead: a caller that starts a blast waits until then.
- `marks` are sub-windows: `--mark <label>` opens one on the open arm (`begin` = now, `end` null),
  `--end-mark <label>` ends it, and the next `--mark`, the next arm or `--close-arm` ends an open
  one. Labels follow the arm-name rule and are unique within an arm. These commands contact no node.
- When every node already has the arm (the file and its running switches), nothing restarts and the
  arm is still recorded, with `begin` = now by the operator's clock, `"no_restart": true` and `ready`
  = `begin`. The tool first prints each node's `PARAMS_CURRENT` (and `SWITCHES_CURRENT`) line from
  what phase A read, and refuses (nothing recorded) when one of them disagrees or a node's container
  is not running.
- `failed: <node>` appears when the run stopped at that node.

An arm name is `[a-z0-9-]` and unique in the record. `report/provenance.py` accepts a logged value
when it is the fleet value, the node's step-9 override, or a value an arm begun by then set for
that node. `report/make_bundle.py` publishes the arms as rows in `consensus.param_arms` (it reads
`name`, `begin`, `end`, `nodes` and `failed`), and `tools/cert-rate.py --windows` cuts its windows
from them.

### Resuming after a failure

1. Read why: the `PA_FAIL` line, then the node itself (`sudo systemctl status <unit>`,
   `sudo cat /var/lib/bench-logs/arm-units/<unit>.out`, `sudo docker logs --tail 200 telcoin`).
   The unit has started the node again whatever failed after its stop.
2. Fix the cause. To undo the failed node instead, use the rollback line the tool printed.
3. Run the same arm again under a new name, for example
   `--arm-file benchmark/arms/v-vote.arm --arm v-vote-r2`. Nodes already in the arm (their file and
   their running switches match it) are not restarted; the failed node and the ones after it are.
   The record keeps the failed entry, closed by the new one's `begin`.

A guard that deferred twice or an epoch wait that gave up left the node as it was; run again once
the committee or the epoch allows it.

### Host steps

The arm file's `host read-ahead-kb <n>` and `host evict-mdbx` run in the unit, between the stop and
the start (read-ahead first, the eviction last). The function that writes them is
`host_steps_hook` in `params-apply.sh`, between the `HOOK` marker lines; its comment is the
contract. Until it is filled in, an arm that lists a host step is refused with
`host steps not available` before any node is contacted (a dry run prints its plan first), and
every arm file from `p1-mdbx-advice` on is refused that way. An arm with a host step restarts every
node.

## propose-latency

`propose-latency.py` measures, per validator, the time from `header proposed` to the node's own
`quorum reached` (C), the round period, and the gap from a quorum to the next proposal. It is the
calibration input of `cadence-model.py`.

```
propose-latency.py --logs <dir> [--node-glob GLOB] [--node-name-regex RE] [--windows MANIFEST | --from ISO --to ISO]
```

File selection matches `cert-rate.py`: every `bench-validator-*.log.gz` in the directory, grouped
by node with `^(bench-validator-[0-9]+)-`. A restart-per-arm sweep splits a node's history over the
`telcoin-pre-arm-<arm>-<UTC>` logs, the last container's `telcoin` log and the `unit-stdout` file,
and the same lines appear in more than one of them; an event line counts once per node, and
proposals pair with quorums by (epoch, round). `--windows` prints one table per `param_arms[]` and
`phases[]` entry plus a `run` table (an arm with no `end` is left out). `--from`/`--to` take full
UTC times (`2026-10-06T23:50:00Z`); `HH:MM:SS` is accepted only when every event falls on one UTC
day, so a window across midnight needs the date. Under each table, a node with no event in the
window is named with the span its files cover. Its rate shows `—` rather than 0.
