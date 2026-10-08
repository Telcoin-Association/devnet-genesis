# Run analysis tools

Two stdlib-only Python scripts that read what a benchmark run leaves in `results/<run>/` and
answer the first questions after a run: did every validator get its headers certified, and how
fast did rounds, blocks and transactions move in each phase. They also run against logs pulled
from devnet or testnet. Neither tool talks to GCP; `block-rate.py` reaches Prometheus only when
given `--prom-url`.

The harness runs both after `collect`, at deploy step 15, and at the end of the teardown once the
node logs are on disk (`bench_local_analysis` in `bench-lib.sh`). The output lands in
`results/<run>/analysis/cert-rate.md` and `block-rate.md`. A failure there is a warning and never
stops the collect or the teardown.

## cert-rate.py

```
python3 benchmark/tools/cert-rate.py --logs results/<run>/logs --windows results/<run>/manifest.json
```

It reads every file in `--logs` whose name matches `--node-glob` (default
`bench-validator-*.log.gz`, gzip or plain text) and groups the files by node: group 1 of
`--node-name-regex` (default `^(bench-validator-[0-9]+)-`) on the file name. The default takes
each validator's container logs, the logs saved on the node before a restart or kill
(`-telcoin-pre-step9-…`, `-telcoin-pre-kill-…`) and the unit's stdout file
(`-unit-stdout.log.gz`, the only copy of the seconds between a pre-kill save and the kill). An
event line found in two files of the same node counts once.

Per node and window, from the default log filter:

| column | log line | meaning |
|---|---|---|
| proposed | `header proposed` | own headers proposed, re-proposals included |
| quorum | `quorum reached` | own headers that formed a certificate |
| rate % | | quorum / proposed |
| re-proposals | `re-proposing last header` | |
| vote errors | `failed to get vote for header` | every failed vote request |
| canceled | the same, ending `): Canceled` | requests cancelled because a newer proposal replaced the header |
| could not form | `Could not form a certificate` | |
| subdags | `subdag committed` | subdags this node committed |
| certs committed | `certificate committed` | certificates this node committed |
| own cert % | `certificate committed … origin=` | share of the window's committed certificates that are this node's |
| own leader % | the same, at round == `leader_round` | share of the window's committed leaders that are this node's |
| not committed % | `quorum reached` vs `certificate committed` | own certificates formed in the window that the node never logged as committed |

A fleet row adds the counts up. The fair share for the two share columns is 100 / committee size;
the report prints the committee size it saw committing in each window.

### How the share columns are derived

A node's authority id comes from the `auth=` field of its certifier lines (the most frequent
value), or from `--authority NODE=ID` when the log has none. Without an id the share columns stay
empty and the report says so.

Each `subdag committed` line follows the `certificate committed` lines of its subdag. The leader is
the one certificate of that subdag at round `leader_round`. The subdag's epoch is
`subdag_index >> 32`, which keys a committed certificate as (epoch, round, origin). An own
certificate (`quorum reached … round= epoch=`) that never shows up under the node's own origin is
"not committed": no committed leader reached it. Certificates formed after the node's last logged
commit are left out, since their commit may not be logged yet. A node that was down does not log
the commits made while it was away, so its own certificates committed in that time count as not
committed.

"Not committed" is the default-filter stand-in for orphans. A strict orphan count (certificates no
later header lists as a parent) needs every header's parent list, which only debug logging prints:
run the nodes with a log filter including `primary=debug` for that.

### Windows

- `--windows MANIFEST`: `manifest.param_arms[]` (`{name, begin|start, end}`) and
  `manifest.phases[]` (`{name, start, end}`), plus one `run` window from the first start to the
  last end. A manifest with neither falls back to buckets, with a note.
- `--from ISO --to ISO`: one window.
- `--bucket-min N` or nothing: the whole log in N-minute buckets (default 10).

`--format md` (default) prints one table per window, `json` the same numbers with full authority
ids, `csv` one row per window and node. Exit status 0 = report written, 1 = bad arguments or
unreadable input, 2 = no file matched the glob.

### r20261006-0458

Run window (06:05:38 to 06:52:08 UTC), about 12 s to compute:

| node | rate % | own cert % | own leader % | not committed % |
|---|---:|---:|---:|---:|
| bench-validator-03 | 47.1 | 4.0 | 0.1 | 34.0 |
| bench-validator-04 | 52.9 | 4.7 | 0.8 | 30.5 |
| the other eight | 90.3 to 98.3 | 10.7 to 12.4 | 11.2 to 14.2 | 1.3 to 7.5 |

In the 40-minute mixed phase v03 and v04 certified 60.4 % and 67.8 % of their headers. The rates
match the hand count in `tasks/stall/A2-logs.md`; reading the unit stdout log adds v05's 21
proposals from the 28 s before its kill.

### Devnet and testnet logs

`common/download-logs.sh` writes plain-text `<instance>-clean.log` files:

```
python3 benchmark/tools/cert-rate.py --logs <dir> --node-glob '*-clean.log' \
    --node-name-regex '^(.+)-clean\.log$' --from 2026-10-06T06:00:00Z --to 2026-10-06T07:00:00Z
```

Timestamps are read from a leading `ts=<ISO>` (logfmt) or a leading ISO time. Add
`--authority <instance>=<id>` for a node whose log has no certifier line with an `auth=` field.

## block-rate.py

```
python3 benchmark/tools/block-rate.py --run results/<run>
python3 benchmark/tools/block-rate.py --sampler results/<run>/sampler/bench-validator-01.csv --bucket-min 5
```

One table per window with a row per source; a column stays empty (`–`) when no source has it.

| row | source | columns |
|---|---|---|
| chain | `blasters/*.json` `.blocks` (number, timestamp, epoch, round, tx_count), de-duplicated by block number | committed rounds/s, blocks/s, tx/s |
| each node | `sampler/<node>.csv` (`ts_unix`, `block`) | blocks/s |
| each node | `metrics.json` `prometheus.series` | rounds/s (`tn_primary_round`), committed rounds/s (`tn_primary_committed_round`), commit latency p50 / p95 (`tn_primary_commit_latency_seconds`) |

- Chain committed rounds/s: the leader-round advance between consecutive blocks; the first block
  of a new epoch adds its own round, since rounds restart each epoch. Blocks exist only for
  non-empty outputs, so the rounds between two blocks are credited to the later one.
- Chain blocks/s and tx/s: the blocks timestamped in the window and their `tx_count`, per second.
- Sampler blocks/s: (last block - first block) / (last ts - first ts) over the window's samples.
- Gauge rounds/s: the increase over the window's points per second. A drop (new epoch or restart)
  adds nothing, and neither does a step faster than 10x the window's median step: a restarted
  node jumping to the current round as it catches up.
- Commit latency: the median of the p50 and p95 points in the window.

`node-sampler.sh` records only the block number, no consensus round and no transaction count, so
rounds come from `metrics.json` (deploy step 15) or Prometheus, and transactions from the
blasters' block lists. Windows are as for `cert-rate.py`; with `--run` and no window option the
run's `manifest.json` is used when present. `--format json` prints the same numbers. Exit status
0 = report written, 1 = bad arguments or unreadable input, 2 = no data at all.

### Prometheus instead of metrics.json

```
BENCH_PROM_AUTH=<user>:<password> python3 benchmark/tools/block-rate.py --run <dir> \
    --prom-url https://<grafana>/api/datasources/proxy/uid/<prometheus uid>/api/v1 \
    --prom-selector '{network="devnet"}' --from <ISO> --to <ISO>
```

The URL is the Prometheus HTTP API base (the part before `/query_range`); queries use a 15 s step.
`BENCH_PROM_AUTH`, when set, is sent as HTTP basic auth. For devnet or testnet, `--run` may be an
empty directory: the node rows then come from Prometheus alone.

## Series the collector should request

`metrics.json` comes from `tn-transaction-generator/bench/collect-gcp-metrics.py`, which already
requests `tn_primary_round`, `tn_primary_committed_round`, `tn_primary_subdags_committed_total`
and `tn_primary_commit_latency_seconds`. The node also exports, from
`crates/consensus/primary/src/metrics.rs` (scope `tn_primary`): `tn_primary_headers_proposed_total`,
`tn_primary_certificates_formed_total`, `tn_primary_votes_received_total`,
`tn_primary_vote_request_failures_total` (counters) and `tn_primary_certificate_form_duration_seconds`
(histogram). With them the certification rate can be read from Prometheus without the logs. They
must be requested as optional series: a missing non-optional series makes the collector exit 2,
which aborts deploy step 15.
