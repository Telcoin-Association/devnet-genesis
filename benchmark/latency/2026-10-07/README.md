# Internal vs external inter-zone latency, 2026-10-07

Measured with `benchmark/tools/latency-probe.sh --addresses both` (run `20261007T025234Z`, 02:52 to
02:56 UTC, cleanup done 02:56). Tables made with `benchmark/tools/latency-matrix.py`; see
`benchmark/tools/README.md` ("Latency probe") for what each file means. The raw per-zone JSON stays
in the gitignored `benchmark/results/latency/20261007T025234Z/`.

```bash
benchmark/tools/latency-probe.sh --project <project> --machine-type e2-small --addresses both \
    --zones us-west2-a,europe-west2-b,australia-southeast1-c,asia-northeast1-b,northamerica-northeast1-b,europe-west4-a,asia-southeast1-b,asia-east2-a,asia-northeast3-a,asia-south1-c
benchmark/tools/latency-matrix.py benchmark/results/latency/20261007T025234Z --out benchmark/latency/2026-10-07 \
    --layout final=<the same ten zones>
```

## Why

Stage-1 bench r20261006-2058 measured consensus vote round trips between Europe and Asia that equal
2 x (RTT to Los Angeles + RTT from Los Angeles to the peer), within 7 ms on all 12 links, while Los
Angeles's own links were 2 x the direct RTT. The bench nodes dial each other on ephemeral
Premium-tier external IPs, and the 2026-10-06 probe measured internal IPs only. This run measures
both address kinds at once: if Google's external path from Europe to Asia ran through the US, the
environment would explain the bench numbers; if it does not, the detour happens inside the node.

## Setup

- **Zones (10):** exactly the bench fleet (`final` layout in `benchmark/config.sh`): us-west2-a,
  europe-west2-b, australia-southeast1-c, asia-northeast1-b, northamerica-northeast1-b, europe-west4-a,
  asia-southeast1-b, asia-east2-a, asia-northeast3-a, asia-south1-c. Mumbai zone c had not been probed
  before; 2026-10-06 stood in with asia-south1-a.
- **Probe VMs:** `e2-small`, Debian 12, default VPC, each with an ephemeral external IP on the
  Premium tier (the bench nodes' tier). A temporary rule admitted the ten external /32s on icmp,
  tcp:7777 and udp:7778, as well as the usual source-tag and IAP rules. All were deleted at the end.
- **Per ordered pair and address kind:** 40 pings at 4/s, 40 UDP echoes of 1200 bytes at 4/s (2 s
  timeout), 20 TCP connects at 4/s. Each VM probed every peer's internal and external IP in the same
  pass, so the two numbers for a pair come from the same seconds on the same VM.
- **Skipped zones:** none. **Failed zones:** none. **UDP loss:** none, on 90 ordered pairs x 2
  address kinds. ICMP lost 1 or 2 of about 40 pings on a handful of long pairs, and 18 % on us-west2-a to
  asia-southeast1-b external; UDP and TCP on those pairs lost nothing.

## Headline: the external path does not detour through Los Angeles

No ordered pair is flagged in `external-vs-internal.md` (flag: external median more than 25 % or more
than 30 ms above internal). Across all 90 ordered pairs, external minus internal runs from -33.2 to
+14.9 ms (median +0.6 ms). On the 24 Europe-Asia directions it runs from -24.1 to +14.9 ms (median
+0.8 ms).

UDP echo medians, one direction (ms). `via LA` = external RTT(src, us-west2-a) + external RTT(us-west2-a,
dst):

| src → dst | internal | external | via LA |
|---|---:|---:|---:|
| London → Tokyo | 257.02 | 238.90 | 238.83 |
| London → Seoul | 261.84 | 265.21 | 265.65 |
| London → Sydney | 275.42 | 276.02 | 276.74 |
| London → Hong Kong | 198.87 | 202.14 | 281.73 |
| London → Singapore | 166.18 | 169.17 | 307.04 |
| London → Mumbai (c) | 144.62 | 154.29 | 356.63 |
| Netherlands → Tokyo | 258.10 | 249.51 | 250.59 |
| Netherlands → Seoul | 230.09 | 227.00 | 277.41 |
| Netherlands → Sydney | 313.14 | 328.01 | 288.50 |
| Netherlands → Hong Kong | 199.38 | 196.25 | 293.49 |
| Netherlands → Singapore | 161.64 | 167.35 | 318.80 |
| Netherlands → Mumbai (c) | 148.34 | 155.96 | 368.39 |
| LA → Tokyo | 100.48 | 101.33 | — |
| LA → Seoul | 127.07 | 128.08 | — |
| LA → Sydney | 137.93 | 139.06 | — |
| LA → Hong Kong | 142.96 | 143.94 | — |
| LA → Singapore | 164.00 | 168.84 | — |
| LA → Mumbai (c) | 220.81 | 218.18 | — |

Reading it:

- External ≈ internal on every link. The external path is not the detour.
- For Hong Kong, Singapore and Mumbai the via-LA sum is 80 to 220 ms above the direct external RTT,
  so these six links decide the question. The network gives about 145 to 205 ms. A vote round trip
  equal to 2 x the via-LA sum on these links is therefore not the network, and the cause is inside
  the node (for example, the vote or its certificate reaching the peer through the LA node).
- For Tokyo, Seoul and Sydney from London (and Tokyo from the Netherlands), the via-LA sum is within
  1 ms of the direct RTT, internal and external. Google's Europe to North-East-Asia path is as long as
  going through LA, so these links cannot tell the two explanations apart.
- Differences of 10 to 30 ms between the internal and external flow of one pair are ECMP path
  choice, not a systematic penalty: London ↔ Tokyo internal TCP connects (fresh source port each)
  span 240.8 to 258.9 ms, and the external UDP flow landed on the faster path. Some external flows are
  faster than internal ones by up to 33 ms (northamerica-northeast1-b → australia-southeast1-c 246.1
  internal, 212.9 external; asia-south1-c ↔ australia-southeast1-c about 241 vs 209).

## Mumbai zone c vs zone a

Internal UDP, direction-averaged (ms). Zone a is from the 2026-10-06 run, zone c from this one, so a
few ms of difference is day-to-day path variation.

| peer | asia-south1-a (10-06) | asia-south1-c (10-07) |
|---|---:|---:|
| us-west2-a | 216.27 | 221.83 |
| europe-west2-b | 149.11 | 142.70 |
| europe-west4-a | 152.09 | 147.22 |
| northamerica-northeast1-b | 223.15 | 224.62 |
| australia-southeast1-c | 231.03 | 241.13 |
| asia-northeast1-b | 120.67 | 123.98 |
| asia-northeast3-a | 120.71 | 121.99 |
| asia-east2-a | 88.16 | 86.74 |
| asia-southeast1-b | 58.59 | 57.57 |

Zone c is within 10 ms of zone a on every link. The stand-in on 2026-10-06 was fair.

## Quorum window

`final` layout, one validator per zone, slowest 6th-nearest UDP RTT: internal 233.51 ms (Sydney,
`kth-nearest-final.md`), external 208.65 ms (Sydney, `kth-nearest-external.md`). Medians are 158.64
internal and 158.82 external. The difference at Sydney is the faster external flows above, so the
external numbers are the ones that match what the bench nodes see.

## Files

- `matrix-{udp,tcp,icmp}.csv/.md`, `tcp-vs-udp.md`, `kth-nearest.md`, `kth-nearest-final.md`:
  internal addresses, same layout as 2026-10-06.
- `matrix-{udp,tcp,icmp}-external.csv/.md`, `kth-nearest-external.md`: external addresses.
- `external-vs-internal.md`: all 90 ordered pairs, internal and external UDP medians, delta, ratio,
  via-LA sum, loss.
- `summary.json`: everything above, machine-readable (`external` block for the external tables).
