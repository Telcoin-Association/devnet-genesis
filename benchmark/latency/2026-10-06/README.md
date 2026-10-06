# Inter-zone latency, 2026-10-06

Measured with `benchmark/tools/latency-probe.sh` (run `20261006T175053Z`, 17:50 to 17:56 UTC, cleanup
done 17:59). Tables made with `benchmark/tools/latency-matrix.py`; see `benchmark/tools/README.md`
("Latency probe") for what each file means. The raw per-zone JSON stays in the gitignored
`benchmark/results/latency/20261006T175053Z/`.

- **Probe VMs:** `e2-small` (Debian 12, internal IPs only, default VPC) in every zone. No fallback to
  `e2-micro` was needed.
- **Per ordered pair:** 40 pings at 4/s, 40 UDP echoes of 1200 bytes at 4/s (2 s timeout), 20 TCP
  connects at 4/s.
- **Skipped zones:** none. **Failed zones:** none. **UDP loss:** none on any pair.
- **Zones (18):**
  - current fleet: us-west2-a, australia-southeast1-c, northamerica-northeast1-b, europe-west4-a,
    europe-west2-b
  - new candidates: asia-northeast1-b, asia-southeast2-a, asia-east2-a, asia-northeast3-a, asia-south1-a
  - alternates: asia-southeast1-b, asia-northeast2-a, australia-southeast2-a, europe-west3-a,
    southamerica-east1-a, me-west1-b, asia-northeast1-c, asia-northeast3-b

Layouts (10 validators each; a zone listed twice holds two validators):

- `old`: us-west2-a, australia-southeast1-c, northamerica-northeast1-b, europe-west4-a, europe-west2-b,
  two validators in each. Intra-zone RTT was not measured and is taken as 1 ms.
- `new`: us-west2-a, europe-west2-b, australia-southeast1-c, asia-northeast1-b,
  northamerica-northeast1-b, europe-west4-a, asia-southeast2-a, asia-east2-a, asia-northeast3-a,
  asia-south1-a, one validator each.

| layout | slowest validator's 6th-nearest UDP RTT | median 6th-nearest | slowest 5th-nearest |
|---|---:|---:|---:|
| old | 314.00 ms (australia-southeast1-c) | 137.85 ms | 232.83 ms |
| new | 231.03 ms (australia-southeast1-c) | 162.11 ms | 199.51 ms |

Reading notes:

- A cell averages two one-way flows. On long paths the two flows can sit on different ECMP paths:
  australia-southeast1-c to europe-west2-b measured 301.0 ms one way and 327.0 ms the other, and TCP
  connects (a fresh source port each) between them landed at about 275, 301 and 327 ms. A QUIC
  connection keeps one path for its lifetime, so which RTT a validator pair gets depends on its
  port hash.
- The five "UDP > TCP by >10%" flags are all short pairs: two same-region pairs under 1 ms, where the
  user-space UDP echo adds about 0.1 ms that a kernel-only TCP handshake does not, and three 13 to
  22 ms pairs whose TCP range shows a faster path that the UDP flow was not hashed onto.

- `final` (the layout benchmark/config.sh now carries): us-west2-a, europe-west2-b, australia-southeast1-c,
  asia-northeast1-b, northamerica-northeast1-b, europe-west4-a, asia-southeast1-b, asia-east2-a,
  asia-northeast3-a, asia-south1-c. Jakarta offers no c3-highcpu-8, so Singapore replaces it; Mumbai's
  c3 zone is c, which was not probed, so asia-south1-a stands in for it (same region, same metro).
  Table: `kth-nearest-final.md` (slowest 6th-nearest 231.03 ms, Sydney; median 158.01 ms).
