# Inter-zone latency for the bench-5 fleet (incl. us-east4), 2026-11-07

Measured with `benchmark/tools/latency-probe.sh --addresses both` (run `20261107T145111Z`, 14:51 to
14:54 UTC, cleanup done 14:54). Tables made with `benchmark/tools/latency-matrix.py`; see
`benchmark/tools/README.md` ("Latency probe") for what each file means. The raw per-zone JSON stays
in the gitignored `benchmark/results/latency/20261107T145111Z/`.

```bash
benchmark/tools/latency-probe.sh --project <project> --machine-type e2-small --addresses both \
    --zones us-west2-a,europe-west2-b,australia-southeast1-c,asia-northeast1-b,us-east4-b,europe-west4-a,asia-southeast1-b,asia-east2-a,asia-northeast3-a,asia-south1-c
benchmark/tools/latency-matrix.py benchmark/results/latency/20261107T145111Z --out benchmark/latency/2026-11-07 \
    --layout final=<the same ten zones>
```

## Why

The 2026-10-07 matrix has no us-east4 row: validator-05 moved from northamerica-northeast1-b to
us-east4-b (Ashburn) after a c3 stockout before bench 3, and every run since (r20261103-1922,
r20261105-0803, bench 5) has used that zone. This run measures the ten zones the bench-5 fleet
actually occupies, internal and external at once, as a pre-run gate for bench 5 and as the RTT
reference for its per-stage latency analysis.

## Headline numbers (from `latency-matrix.py`)

- widest UDP pair: europe-west2-b <-> australia-southeast1-c, 301.56 ms
- flagged pairs (external path far from internal): 0 of 45
- external slower than internal: 1 of 90 ordered pairs (`external-vs-internal.md`)
- layout `final`: slowest 6th-nearest neighbour 209.89 ms, at us-east4-b (`kth-nearest-final.md`)
