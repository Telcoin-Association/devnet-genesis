# Admission metrics fixtures

Each `.prom` file is the `/metrics` body of one node, unfiltered, in the form the exporter writes
it, followed by the `NODE_MODE=<mode>` line that `bench_admission_read` appends (contract C3).
Filtering a file with the C3 regex

    ^tn_network_(admission_mode|admission_fallback|closed_admission_denied_total)[{ ]

and keeping the last line gives exactly what `bench_admission_read` prints. `bench_admission_parse`
must give the same result on the filtered and the unfiltered text, so the files include `# HELP` /
`# TYPE` lines and some decoy families:

- `tn_network_source_admission_denied_total` has a `direction` label and ends in
  `admission_denied_total`. It must not count toward `denied_in` or `denied_out`.
- `tn_network_admission_resolved_current`, `_required_current` and `_contradicted` share the
  `tn_network_admission_` prefix.
- The HELP line of `tn_network_admission_mode` ends in `Closed = 2.`

## Where the shapes come from (telcoin-network 3f9b0709)

All paths are in `crates/network-libp2p/src/metrics.rs` unless noted.

- `:1264-1281`: `#[derive(Metrics)] #[metrics(scope = "tn_network")] struct PeerManagerMetricHandles`
  with `admission_mode: Gauge` (:1269) and `admission_fallback: Gauge` (:1279). The derive joins
  scope and field with `.`, and the exporter rewrites `.` to `_`, so the families are
  `tn_network_admission_mode` and `tn_network_admission_fallback`. The derive registers the doc
  comment as the description, so both gauges get a `# HELP` line with that text.
- `:1376`: the handles are built with `new_with_labels(&[("network", network)])`. The only label is
  `network`.
- `:26-31` `network_label`: `NetworkType::Primary` gives `primary`, `NetworkType::Worker(id)` gives
  `format!("worker-{id}")`. The node runs worker 0, so the label value is `worker-0`.
- `:1339-1345`: mode is Open = 0, Grace = 1, Closed = 2. `:1358-1363`: fallback is healthy = 0,
  missing = 1, stale = 2, contradictory = 3, unresolved = 4.
- `:1397-1402`: `metrics::counter!("tn_network.closed_admission_denied_total", "network" => ..,
  "direction" => ..)`. Labels come out in that order: `network`, then `direction`. No
  `describe_counter!` exists for it, so it has a `# TYPE` line and no `# HELP` line.
- `:492-498` `ConnectionDirection::label`: `in` and `out`. `KeyedCounters` registers every
  (network, direction) series at zero (doc comment at `:1371-1372`), so all four series exist even
  when nothing was denied.
- `crates/types/src/primary/node_mode.rs:13`: `tn_nodeMode` is one of `CvvActive`, `CvvInactive`,
  `Observer`.

## Number rendering

`metrics-exporter-prometheus` 0.18.1 (Cargo.lock) writes every value with `to_string()`. Gauges are
`f64` and Rust prints `2.0_f64` as `2`, so a live node shows `2`, `1` and `0`, never `2.0`.
Counters are `u64`. The exporter adds no timestamps, and `tn-metrics` sets no global labels
(`crates/tn-metrics/src/recorder.rs`). Family order and series order come from a `HashMap` and
change between scrapes. Counter families come first, then gauges, and a blank line ends each family.

`reordered-labels-with-ts.prom` is not live exporter output. It is what a re-exposition can look
like: values as `2.0` / `0.0`, a millisecond timestamp after every value, an extra
`instance="127.0.0.1:9101"` label, `direction` before `network`, and runs of spaces, tabs and
trailing blanks between fields. Its meaning is the same as `closed.prom`.

## Expected parse and verdict

Closed means `mode_primary = 2`, `mode_worker = 2`, `fallback_n >= 1` and `fallback = 0`.

| fixture | filtered lines | mode_primary | mode_worker | fallback | fallback_n | denied_in | denied_out | node_mode | verdict |
|---|---|---|---|---|---|---|---|---|---|
| `closed.prom` | 8 | 2 | 2 | 0 | 2 | 3 | 1 | CvvActive | `ADM_OK`, Closed |
| `grace-worker.prom` | 8 | 2 | 1 | 0 | 2 | 0 | 0 | CvvActive | `ADM_BAD`: worker mode 1 (Grace), not 2 |
| `fallback-active.prom` | 8 | 2 | 2 | 1 | 2 | 0 | 0 | CvvActive | `ADM_BAD`: fallback 1 (missing), not 0 |
| `missing-worker.prom` | 4 | 2 | `-` | 0 | 1 | 0 | 0 | Observer | `ADM_BAD`: no worker series |
| `reordered-labels-with-ts.prom` | 8 | 2 | 2 | 0 | 2 | 3 | 1 | CvvActive | `ADM_OK`, Closed |

The expected `ADM_OK` line for both Closed fixtures is
`ADM_OK <inst> primary=2 worker=2 fallback=0 denied_in=3 denied_out=1 mode=CvvActive`.

The denial counts are split across networks so the parser has to sum them: `in` is primary 2 plus
`worker-0` 1, and `out` is primary 1 plus `worker-0` 0.

## Notes on the not-Closed cases

- `grace-worker.prom`: `worker-0` at Grace with fallback 0 is what a worker configured for Grace
  reports (`crates/network-libp2p/src/peers/admission.rs:238-240`). A worker configured for Closed
  that falls back to Grace would also show fallback 4.
- `fallback-active.prom`: Closed with fallback 1 cannot come out of one `set_admission` call,
  because a fallback forces the effective mode to Grace or Open (`admission.rs:238-247`). A scrape
  can still see it. `set_admission` sets the mode (`metrics.rs:1345`) before the fallback
  (`:1358`), so a node recovering from Open/missing to Closed has a short window where the scrape
  shows mode 2 and fallback 1. The gate has to check the fallback separately from the mode.
- `missing-worker.prom`: no `worker-0` line in any family. `mode_worker` is `-`, and `fallback_n`
  counts only the primary series.
