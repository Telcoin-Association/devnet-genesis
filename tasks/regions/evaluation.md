# Bench fleet regions: live evaluation (2026-10-06)

Project `tn-devnet`, read-only `describe`/`list` calls only, every one under
`perl -e 'alarm shift; exec @ARGV' <secs> gcloud … </dev/null`. Account `grant@telcoin.org`.

## What the fleet asks of a zone and a region

Read from the harness, not assumed:

| Item | Value | Source |
|---|---|---|
| Node machine type | `c3-highcpu-8` (8 vCPU, 16 GB), validators and observer | `benchmark/config.sh` `MACHINE_TYPE="${BENCH_MACHINE_TYPE:-c3-highcpu-8}"` |
| Node boot disk | 100 GB `hyperdisk-balanced`, 20000 IOPS, 800 MiB/s provisioned | `NODE_DISK_SIZE`, `NODE_DISK_TYPE`, `NODE_DISK_IOPS`, `NODE_DISK_THROUGHPUT` |
| Node address | one ephemeral external IP each (`USE_STATIC_IPS=0`), `subnet=default` | `benchmark/config.sh`, `common/create-instances.sh` |
| Blaster | `e2-standard-2`, 20 GB `pd-balanced` boot, ephemeral external IP | `benchmark-blast.sh` `create_vm` |
| Blaster placement | one per validator (`bench-blaster-01..10`) in that validator's zone `ZONES[k]`; none for the observer | `benchmark-blast.sh` `do_run` |
| Funder | one `bench-funder` in `ZONES[0]`, deleted after `fund` (never alongside the blasters) | `benchmark-blast.sh` `do_fund` |

So a region with one validator needs 8 `C3_CPUS`, 2 blaster vCPUs, 2 in-use addresses, 100 GB /
20000 IOPS / 800 MiB/s of hyperdisk-balanced and 20 GB of `SSD_TOTAL_GB`. `us-west2` (validator-01
plus the observer) needs 16 `C3_CPUS`, 3 addresses and twice the hyperdisk.

## Verdict

Two of the planned zones cannot host the node hardware. Everything else passes.

| Index | Node | Planned zone | Verdict | Zone used |
|---|---|---|---|---|
| 0 | bench-validator-01 | us-west2-a | OK | us-west2-a |
| 1 | bench-validator-02 | europe-west2-b | OK | europe-west2-b |
| 2 | bench-validator-03 | australia-southeast1-c | OK | australia-southeast1-c |
| 3 | bench-validator-04 | asia-northeast1-b | OK | asia-northeast1-b |
| 4 | bench-validator-05 | northamerica-northeast1-b | OK | northamerica-northeast1-b |
| 5 | bench-validator-06 | europe-west4-a | OK | europe-west4-a |
| 6 | bench-validator-07 | asia-southeast2-a (Jakarta) | **UNUSABLE**: no `c3-highcpu-8` in any asia-southeast2 zone (zone a offers only `c3-highmem-{4,8,22,44,88,176}`) | **asia-southeast1-b (Singapore)** |
| 7 | bench-validator-08 | asia-east2-a | OK | asia-east2-a |
| 8 | bench-validator-09 | asia-northeast3-a | OK | asia-northeast3-a |
| 9 | bench-validator-10 | asia-south1-a (Mumbai) | **UNUSABLE**: `c3-highcpu-8` is offered only in asia-south1-c | **asia-south1-c (Mumbai)** |
| 10 | bench-observer-11 | us-west2-a | OK | us-west2-a |

- Mumbai keeps its region; only the zone moves (a to c).
- Jakarta has no listed alternate and no zone that offers the type, so validator-07 moves to
  Singapore, the nearest region that does (all three asia-southeast1 zones offer it). That frees no
  other slot, but it takes Singapore away as Hong Kong's alternate: Hong Kong's alternate is now
  **asia-east1-a (Taiwan)**, checked below. Keeping Jakarta would need `c3-highmem-8` (8 vCPU, 64 GB),
  which the harness cannot express (one `MACHINE_TYPE` for every node) and which breaks "same hardware".
- No quota is short anywhere, so **no quota increase request was filed**.
- A type that `describe` lists can still be out of stock at create time (the 2026-10-06
  e2-standard-2 stockout in australia-southeast1-c). The blaster create path now falls back by
  family on a stockout; the node create path does not (see the orchestrator notes in the W2 summary).

## Zones: machine and disk types

`gcloud compute machine-types describe <type> --zone <z>` and
`gcloud compute disk-types describe hyperdisk-balanced --zone <z>` (the per-zone form of what
`disk_type_check` lists).

| Zone | Role | c3-highcpu-8 | hyperdisk-balanced | e2-standard-2 | n2-standard-2 | n2d-standard-2 |
|---|---|---|---|---|---|---|
| us-west2-a | v01 + observer | OK | OK | OK | OK | OK |
| europe-west2-b | v02 | OK | OK | OK | OK | OK |
| australia-southeast1-c | v03 | OK | OK | OK | OK | OK |
| asia-northeast1-b | v04 | OK | OK | OK | OK | OK |
| northamerica-northeast1-b | v05 | OK | OK | OK | OK | OK |
| europe-west4-a | v06 | OK | OK | OK | OK | OK |
| asia-southeast2-a | v07 (planned) | **not found** | OK | OK | OK | OK |
| asia-southeast2-b | (checked) | **not found** | OK | OK | OK | OK |
| asia-southeast2-c | (checked) | **not found** | OK | OK | OK | OK |
| asia-southeast1-b | v07 (used) | OK | OK | OK | OK | OK |
| asia-east2-a | v08 | OK | OK | OK | OK | OK |
| asia-northeast3-a | v09 | OK | OK | OK | OK | OK |
| asia-south1-a | v10 (planned) | **not found** | OK | OK | OK | OK |
| asia-south1-b | (checked) | **not found** | OK | OK | OK | OK |
| asia-south1-c | v10 (used) | OK | OK | OK | OK | OK |
| asia-northeast1-c | alt for v04 | OK | OK | OK | OK | OK |
| asia-northeast3-b | alt for v09 | OK | OK | OK | OK | OK |
| asia-east1-a | alt for v08 (new) | OK | OK | OK | OK | OK |
| asia-east1-b | (checked) | OK | OK | OK | OK | OK |

`c3-highcpu-8` by zone, from `gcloud compute machine-types list --zones=…`:
asia-south1-c only in asia-south1; asia-south2-b/c; none in asia-southeast2; all of asia-southeast1;
asia-east1-a/b; europe-west3-a/b; southamerica-east1-a; none listed in asia-northeast2 (Osaka),
australia-southeast2 (Melbourne) or me-west1 (Tel Aviv).

`describe` failure text, for the record:
`ERROR: (gcloud.compute.machine-types.describe) Could not fetch resource: - The resource 'projects/tn-devnet/zones/asia-south1-a/machineTypes/c3-highcpu-8' was not found`.

## Regions: quotas

Headroom is `limit - usage` from `gcloud compute regions describe <region> --format=json`.
`regions describe` lists **no hyperdisk quota metric**. The hyperdisk-balanced limits come from
the Cloud Quotas API (`gcloud beta quotas info describe HDB-TOTAL-{GB,IOPS,THROUGHPUT}-per-project-region
--service=compute.googleapis.com`; `details.value` is the value in force), usage from
`gcloud compute disks list` (no hyperdisk-balanced disk exists in the project today).
`e2` vCPUs count against `CPUS`, not `E2_CPUS` (us-west2 runs e2 VMs with `CPUS` usage 9 and
`E2_CPUS` usage 0).

| Region | Nodes | C3_CPUS need / headroom | CPUS (e2 blasters) | N2_CPUS, N2D_CPUS (fallback) | IN_USE_ADDRESSES | SSD_TOTAL_GB (blaster boot) | HDB GB need / limit | HDB IOPS | HDB MiB/s | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| us-west2 | 2 | 16 / 300 | 2 / 1491 | 2 / 500, 2 / 1500 | 3 / 572 | 20 / 40510 | 200 / 40960 | 40000 / unlimited | 1600 / unlimited | OK |
| europe-west2 | 1 | 8 / 300 | 2 / 2996 | 2 / 1500, 2 / 1500 | 2 / 574 | 20 / 40860 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| australia-southeast1 | 1 | 8 / 300 | 2 / 1496 | 2 / 1500, 2 / 500 | 2 / 574 | 20 / 40860 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| asia-northeast1 | 1 | 8 / 100 | 2 / 1500 | 2 / 1500, 2 / 1500 | 2 / 575 | 20 / 40960 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| northamerica-northeast1 | 1 | 8 / 300 | 2 / 1496 | 2 / 1500, 2 / 1500 | 2 / 574 | 20 / 40860 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| europe-west4 | 1 | 8 / 300 | 2 / 2996 | 2 / 1500, 2 / 3000 | 2 / 574 | 20 / 40860 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| asia-southeast1 | 1 | 8 / 300 | 2 / 3000 | 2 / 1500, 2 / 3000 | 2 / 575 | 20 / 40960 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| asia-east2 | 1 | 8 / 300 | 2 / 1500 | 2 / 1500, 2 / 500 | 2 / 575 | 20 / 40960 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| asia-northeast3 | 1 | 8 / 100 | 2 / 1500 | 2 / 1500, 2 / 1500 | 2 / 575 | 20 / 40960 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |
| asia-south1 | 1 | 8 / 300 | 2 / 3000 | 2 / 3000, 2 / 3000 | 2 / 575 | 20 / 40960 | 100 / 40960 | 20000 / unlimited | 800 / unlimited | OK |

Also checked: asia-southeast2 (C3_CPUS 300, CPUS 1500, same HDB limits; quota was never the
problem there) and asia-east1 (C3_CPUS 300, CPUS 3000, N2 1500, N2D 3000), so the Taiwan alternate
fits too. Project-wide: `CPUS-ALL-REGIONS-per-project` 3000 and `IN-USE-ADDRESSES-per-project` 575
(Cloud Quotas defaults; the whole fleet with blasters is 108 vCPUs and 21 addresses). Per-zone
hyperdisk-balanced limits: GB unlimited, IOPS 6,000,000, throughput 2,000,000.

Watch item: asia-south1 lists `E2_CPUS` limit 0 (every other region 600). It does not apply today
(e2 counts against `CPUS`), but if Google moves e2 accounting onto `E2_CPUS`, an e2 blaster in
Mumbai fails on quota, and the blaster fallback only covers stockouts.

No `gcloud beta quotas preferences` exist on the project (`preferences list` returned `[]`).

### Quota increase requests

None filed: no region is SHORT. Had one been, the request would be
`gcloud beta quotas preferences create --project=tn-devnet --service=compute.googleapis.com
--quota-id=<id, e.g. C3-CPUS-per-project-region> --dimensions=region=<region> --preferred-value=<n>
--email=grant.kee@telco.in --justification='…'` (quota ids from
`gcloud beta quotas info list --service=compute.googleapis.com`: `C3-CPUS-per-project-region`,
`CPUS-per-project-region`, `IN-USE-ADDRESSES-per-project-region`, `HDB-TOTAL-GB-per-project-region`,
`HDB-TOTAL-IOPS-per-project-region`, `HDB-TOTAL-THROUGHPUT-per-project-region`).

## Network

`gcloud compute networks describe default`: `autoCreateSubnetworks: True` (mode AUTO). The default
network has a subnet in every fleet region (42 regions in all):

| Region | Subnet |
|---|---|
| us-west2 | 10.168.0.0/20 |
| europe-west2 | 10.154.0.0/20 |
| australia-southeast1 | 10.152.0.0/20 |
| asia-northeast1 | 10.146.0.0/20 |
| northamerica-northeast1 | 10.162.0.0/20 |
| europe-west4 | 10.164.0.0/20 |
| asia-southeast1 | 10.148.0.0/20 |
| asia-east2 | 10.170.0.0/20 |
| asia-northeast3 | 10.178.0.0/20 |
| asia-south1 | 10.160.0.0/20 |
| asia-southeast2 / asia-east1 | 10.184.0.0/20 / 10.140.0.0/20 |

Every subnet is inside `default-allow-internal` (10.128.0.0/9), which carries the blaster to node
RPC traffic on internal IPs. The bench consensus rule is built from each node's own /32s
(`benchmark-firewall.sh consensus_sources`), so it needs no change for new regions.

## Zones list

`gcloud compute zones list --filter='region:(…)' --format='table(name,status)'`: every zone of the
ten fleet regions (and asia-southeast2) is `UP`:

```
europe-west4-a/b/c, europe-west2-a/b/c, asia-southeast1-a/b/c, asia-northeast1-a/b/c,
asia-south1-a/b/c, australia-southeast1-a/b/c, asia-east2-a/b/c, asia-northeast3-a/b/c,
asia-southeast2-a/b/c, northamerica-northeast1-a/b/c, us-west2-a/b/c        all UP
```

## gcloud notes

- `gcloud compute disk-types list --filter='name=hyperdisk-balanced AND zone:(…)'` (the form
  `disk_type_check` uses) still matches, but prints `WARNING: --filter : operator evaluation is
  changing for consistency across Google APIs. name=hyperdisk-balanced currently does not match but
  will match in the near future.` The new `machine_type_check` uses one `describe` per zone instead.
- `gcloud compute machine-types list --filter='… zone ~ ^(…)'` crashed gcloud
  (`TypeError: 'NoneType' object is not iterable`); `--zones=a,b,c` works.

## Dry-run plan with the new ZONES

`BENCH_RUN_ID=r20261006-2359 benchmark/benchmark-deploy.sh --with-contracts` (no `--yes`: no GCP call, no
results directory), trimmed:

```
==========================================
benchmark deploy — run r20261006-2359, project tn-devnet, chain 32286
==========================================
PLAN for run r20261006-2359 (nothing below has been executed):
  …
  fleet    11 x c3-highcpu-8, 100 GB hyperdisk-balanced (provisioned 20000 IOPS, 800 MiB/s), tag bench-node, labels benchmark=1,network=bench,bench-run=r20261006-2359
  load     us-west2-docker.pkg.dev/tn-devnet/txgen/tn-transaction-generator:blast-v2-9f61303, COS blasters x 600 senders on e2-standard-2 -> n2-standard-2 -> n2d-standard-2 (next type on a zone stockout), bucket gs://tn-devnet-bench-r20261006-2359
  results  benchmark/results/r20261006-2359
    bench-validator-01   validator  us-west2-a                 bench01 0xc7d975abd962345e9a6024aab692f6bf19140f03
    bench-validator-02   validator  europe-west2-b             bench02 0x92862b13608e00925551233f21b6f44f6acc7f91
    bench-validator-03   validator  australia-southeast1-c     bench03 0x3205c561e8183aae91ef1ab26a1db3fea83bb120
    bench-validator-04   validator  asia-northeast1-b          bench04 0x213aff13862c86b3159a9552cc2424b92f8cfcfc
    bench-validator-05   validator  northamerica-northeast1-b  bench05 0x31faf1673f324c688fff60172099f944171d6ab3
    bench-validator-06   validator  europe-west4-a             bench06 0xe47fbdfdedadd35501eb7c3f38884238bf251103
    bench-validator-07   validator  asia-southeast1-b          bench07 0x58114823ab8b21c4162cc28472ff2a6810e123e2
    bench-validator-08   validator  asia-east2-a               bench08 0x8e7abe6740a452ade8f02a1f005002976e77fb0a
    bench-validator-09   validator  asia-northeast3-a          bench09 0xc2f61840713de91b60e5b5c404350d705877911e
    bench-validator-10   validator  asia-south1-c              bench10 0x52791a4607b5944ec0da0828d0ee78205b208ef1
    bench-observer-11    observer   us-west2-a                 bench11 0xe88cc26183754978af15a67c1597324eec9ec806
    11 instances in 10 zones, 10 regions


   0  preflight      tools, auth, NO leftover bench-*/benchmark=1 instance|disk|rule|bucket, accounts, empty genesis/,
                     bench-node tag hygiene, obs-devnet df over IAP (< 70%),
                     machine types, disk type and quota headroom (below; every failure listed in one die),
                     pre-snapshots -> benchmark/results/r20261006-2359/pre-{instances,firewall}.json, manifest.json
                     c3-highcpu-8 must exist in every zone it is created in (asia-east2-a asia-northeast1-b asia-northeast3-a asia-south1-c asia-southeast1-b australia-southeast1-c europe-west2-b europe-west4-a northamerica-northeast1-b us-west2-a)
                     + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe c3-highcpu-8 --zone=<each zone> --project=tn-devnet --format='value(name)'
                       (dry run — not executed)
                     e2-standard-2 must exist in every zone it is created in (asia-east2-a asia-northeast1-b asia-northeast3-a asia-south1-c asia-southeast1-b australia-southeast1-c europe-west2-b europe-west4-a northamerica-northeast1-b us-west2-a)
                     + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe e2-standard-2 --zone=<each zone> --project=tn-devnet --format='value(name)'
                       (dry run — not executed)
                     hyperdisk-balanced must be offered in every fleet zone (asia-east2-a asia-northeast1-b asia-northeast3-a asia-south1-c asia-southeast1-b australia-southeast1-c europe-west2-b europe-west4-a northamerica-northeast1-b us-west2-a)
                     + perl -e alarm\ shift\;\ exec\ @ARGV 120 gcloud compute disk-types list --project=tn-devnet --filter=name=hyperdisk-balanced\ AND\ zone:\(<the 10 zones>\) --format=value\(zone.basename\(\)\)
                       (dry run — not executed)
                     quota headroom (limit - usage) in each region must cover its nodes plus one blaster per validator:
                       asia-east2: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       asia-northeast1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       asia-northeast3: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       asia-south1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       asia-southeast1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       australia-southeast1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       europe-west2: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       europe-west4: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       northamerica-northeast1: C3_CPUS 8, CPUS 2, IN_USE_ADDRESSES 2, HDB_TOTAL_GB 100, HDB_TOTAL_IOPS 20000, HDB_TOTAL_THROUGHPUT 800, SSD_TOTAL_GB 20
                       us-west2: C3_CPUS 16, CPUS 2, IN_USE_ADDRESSES 3, HDB_TOTAL_GB 200, HDB_TOTAL_IOPS 40000, HDB_TOTAL_THROUGHPUT 1600, SSD_TOTAL_GB 20
                     + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute regions describe <each region> --project=tn-devnet --format=json
                     + perl -e 'alarm shift; exec @ARGV' 60 gcloud beta quotas info describe HDB-TOTAL-<GB|IOPS|THROUGHPUT>-per-project-region --service=compute.googleapis.com --project=tn-devnet --format=json
                     + perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disks list --project=tn-devnet --format=json
                       (dry run — not executed)
  …
```

Live rehearsal of the same step-0 checks with `BENCH_APPLY=1` (read-only; the functions extracted from
`benchmark-deploy.sh`, 2026-10-06): all pass in 61 s, e.g.

```
    ✓ c3-highcpu-8 offered in all 10 zones
    ✓ e2-standard-2 offered in all 10 zones
    ✓ hyperdisk-balanced offered in all fleet zones
    ✓ asia-northeast1 need/headroom: C3_CPUS 8/100, CPUS 2/1500, IN_USE_ADDRESSES 2/575, HDB_TOTAL_GB 100/40960, HDB_TOTAL_IOPS 20000/unlimited, HDB_TOTAL_THROUGHPUT 800/unlimited, SSD_TOTAL_GB 20/40960
    ✓ us-west2 need/headroom: C3_CPUS 16/300, CPUS 2/1491, IN_USE_ADDRESSES 3/572, HDB_TOTAL_GB 200/40960, HDB_TOTAL_IOPS 40000/unlimited, HDB_TOTAL_THROUGHPUT 1600/unlimited, SSD_TOTAL_GB 20/40510
```

With the originally planned zones (asia-southeast2-a, asia-south1-a) the machine type check stops in one
error that names both:

```
❌ c3-highcpu-8 cannot be created in every zone it needs — change ZONES (benchmark/config.sh) or BENCH_MACHINE_TYPE:
     asia-south1-a: not offered in this zone
     asia-southeast2-a: not offered in this zone
```
