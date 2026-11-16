# HB8-4D: what a bench run already saves of the four measures the bench 7 analyses asked for

Read-only inventory of run r20261115-1653 (results `benchmark/results/r20261115-1653/`, private data
`benchmark/private/bench7-r20261115-1653/`). Nothing was built or changed. Tool-call budget: 22; the
checks listed under "Not determined" did not fit.

| # | Measure | Verdict |
|---|---------|---------|
| 1 | Per-node clock offset | NOT SAVED |
| 2 | Host steal time per node per minute | NOT SAVED (only proxies) |
| 3 | Generators' submit counts per minute | SAVED, per second (sum 60 rows) |
| 4 | Each node's worker count | PARTLY: implied by metric labels, not a saved number |

## 1. Per-node clock offset: NOT SAVED

Where I looked, and what is there:
- `manifest.json` has no key matching clock, chrony, ntp or timex. `node_startup.<node>.host` holds kernel, cmdline,
  os_release, image_serial, mem_total_kb, nproc, datadir/mount keys, disk queue settings, vm_* sysctls,
  container_memory_limit_bytes, lru_gen_enabled. No time-sync key. `node_startup.<node>.host_steps` is an empty list.
- `sampler/<node>.csv` header: ts_unix, pid, rss_*, io_*, psi_mem/io/cpu_some_avg10, db_bytes, static_files_bytes,
  epochs_bytes, cache_bytes, epoch_bytes, loadavg1, oom_count, root_used_pct, block. No clock column.
- `persist/<node>.csv` header: disk_*, vm_*, mem_*, memcg_*, proc_*, mdbx_*, tn_lmdb_*, static_files_*. No clock column.
- Endpoint snapshots (`endpoint-snapshots/<node>-metrics-<UTC>.txt.gz`): the node's own exporter on 127.0.0.1:9101.
  Every metric name starts with `tn_` or `reth_` (321 tn_ and 192 reth_ names in validator-01's first snapshot, 5389
  lines); 0 lines start with `process_`, `node_` or `go_`. `grep -i 'timex|clock|ntp|chrony'` finds only
  `tn_engine_evm_timestamp_clamped_total` (HELP text; an EVM-timestamp counter, not a host clock offset).
  `node_timex_offset_seconds` is NOT among them.
- Prometheus export (`prom-export/INDEX.tsv`, 397 metrics): all `tn_` or `reth_`; no timex, ntp or chrony name.
- Harness: `grep -i 'chrony|timedatectl|ntp|/proc/stat|mpstat|vmstat'` over `benchmark/*.sh`, `benchmark/*.py`,
  `benchmark/tools/*`, `tasks/bench8/orch-endpoint-sampler.sh` finds nothing that reads a clock offset
  (the one `vmstat` hit, `benchmark/node-persist-sampler.sh:13` and `:383`, is `/proc/vmstat` for dirty/writeback pages).
- A repo-wide grep (benchmark, tasks/bench8, common; .sh/.py/.yml/.md/.conf) for chrony|timedatectl|steal|node_exporter|
  node_timex|cpu_seconds finds only the bench 8 planning text (`tasks/bench8/no-run-findings.md:150-157`) and a test
  fixture list at `tasks/bench8/tests/test_orch_scripts.py:858`.

Smallest addition: the endpoint sampler already opens one ssh session per node per round
(`tasks/bench8/orch-endpoint-sampler.sh:57-59`, `gcloud compute ssh ... --command 'curl -s --max-time 10
http://127.0.0.1:9101/metrics | gzip -1 | base64 -w0'`, interval 60 s, comment at `:8`: "one ssh per node per round,
`curl` of the node's exporter, nothing else"). Append `chronyc tracking` (or `timedatectl timesync-status` if the image
uses systemd-timesyncd) to that same `--command`, after a separator line, and write it to a second file
`<node>-chrony-<UTC>.txt.gz`. The script's header (`:8`) and its file-naming rule (`:14`) say "nothing else", so
that comment and the read-only claim must be updated with the change. I did not check which time daemon the node image
(Ubuntu 24.04, image_serial 20261105) runs; the command must match it.

## 2. Host steal time per node per minute: NOT SAVED (proxies exist)

Where I looked: same files as measure 1. No `steal`, no `/proc/stat` read, no `cpu_seconds` anywhere. Nothing in the
sampler CSVs, the persist CSVs, the endpoint snapshots or the prom export.

What IS saved and is only a proxy:
- `sampler/<node>.csv` columns `psi_cpu_some_avg10` (pressure stall, avg over 10 s; sample 1.87 at ts 1794763540) and
  `loadavg1` (sample 1.31), every 30 s. PSI CPU "some" rises under steal and under CPU contention alike; it cannot
  separate them.
- `metrics.json` -> `gcp.<node>.cpu_utilization` (type `compute.googleapis.com/instance/cpu/utilization`, unit %,
  60 s points, sample `[1794763846, 6.58485]`, hypervisor-side view) and `gcp.<node>.telcoin_cpu_cores`
  (type `agent.googleapis.com/processes/cpu_time`, sample `[1794763846, 0.365265]`, the node process's cores).
  Neither carries a per-state split.
- `manifest.node_startup.<node>.host.nproc` = 8.

Smallest addition (two options):
- In the same endpoint-sampler ssh command, add `head -1 /proc/stat` (the aggregate `cpu` line; field 8 is steal in
  jiffies, a running total: the per-minute value is the difference of two rounds, at the sampler's 60 s interval).
  One line per round, no new session.
- Or add one more field to `benchmark/node-sampler.sh` (30 s rows, columns listed above) reading the `steal` field of
  `/proc/stat`. I did not read `node-sampler.sh` itself; its header is from the CSV.
- Alternatively, if the Ops Agent's `agent.googleapis.com/cpu/utilization` series (it has a `cpu_state` label with
  `steal`) is added to the metric list that produces `metrics.json` (the 21 keys under `gcp.<node>` are listed in
  the file; steal is not among them). I did not read that collector script.

## 3. Generators' submit counts per minute: SAVED (per second; sum 60 rows for a minute)

- File: `blasters/bench-blaster-NN.json` (10 files, schema `tn-blast/v2`).
- Key: `series.send_per_second`, with `series.send_per_second_columns` =
  `['s','submitted','accepted','resent','resigned','rpc_errors','blocked_senders','inflight','calls','retries',
  'resent_ok','resent_known','resent_err','rpc_err_known','rpc_err_other','rpc_err_transient','rpc_err_nonce_low',
  'rpc_err_fee','stalled_30s','stalled_300s']` and `series.send_per_second_t0_unix`.
- Resolution: 1 s. In bench-blaster-01 there are 2528 rows, t0 = 1794767000 (the warmup start; the mixed phase starts
  at s=120, unix 1794767120).
- Sample: row s=0 `[0, 6952, 6363, 0, 0, 0, 7, 3483, 6363, ...]` (submitted 6952, accepted 6363); mixed row
  s=120 `[120, 2447, 2447, 0, 0, ...]`.
- `series.per_second` is something else: columns `s, own_tx, chain_tx, ...` are LANDED counts, with t0 at the mixed
  phase start (1794767120); do not use it as submit counts.
- Totals per node: `nodes[].submitted`, `nodes[].accepted` (bench-blaster-01 -> bench-validator-01: 2,747,557 each);
  `totals.submitted` 2,740,957 (own, mixed phase) and `preamble.submitted` 6,600.
- Per-transaction timestamps: `blasters/landings-bench-blaster-NN.ndjson.gz`, one JSON per line with `submit_ms`,
  `accept_ms`, `seen_ms`, `block`, `phase`; sample (cut): `{"hash":"0xa417...","type":"preamble","node":
  "bench-validator-01","sender":24,"nonce":0,"submit_ms":1794766993702,"accept_ms":1794766993718,...}`. Per
  `benchmark/tools/arms-summary.py:46-48` this file holds only a 1-in-`run.args.landings_sample` sample of the mixed
  phase for the slow-landing check, so do not count submits from it; use `send_per_second`.
- The harness already reads this series: `benchmark/tools/arms-summary.py:295-301` (`b_send`, `b_send_t0`,
  `b_submitted`) and the "silent" column (`:52`). `benchmark/report/make_bundle.py:1268` reads `submitted` per node.
- The generator log (`blasters/bench-blaster-NN.txgen-<UTC>.log`, 41 lines) has only milestone lines (e.g.
  `preamble: submitted; waiting for landings submitted=6600 accepted=6600`), no per-interval count. Not a source.
- Attribution: each blaster targets one node (`manifest.blasters[].target`, `node_url`), so per-minute submit counts
  by generator are per target node.

No addition needed. A per-minute table is a re-binning of `send_per_second` by `(s + t0) // 60`.

## 4. Each node's worker count: PARTLY (implied, not a saved number)

- No manifest key holds a worker count. `manifest.admission[].mode_worker` = 2 is NOT a count: it is the value of
  `tn_network_admission_mode` for the worker network (`benchmark/bench-lib.sh:3962`, "mode_worker=<int|-> ...
  network label starts with worker"). `node_info_rpc` holds only the http/ws URLs.
- The node's metrics carry a worker id. In validator-01's first endpoint snapshot (and validators 02, 05, 10 and
  observer-11) the only `network=` values are `primary` and `worker-0`, and the only `worker=` value is `0`
  (122 lines carry `worker="0"`; sample `tn_network_dial_failures_total{network="worker-0"} 0`). In the prom export
  every `tn_worker_*` metric I read has 11 series, one per node (e.g. `tn_worker_batch_size_bytes_count 11`,
  `tn_worker_batch_fetch_duration_seconds_count 11`), which is consistent with 1 worker on each of the 11 nodes
  (bench-validator-01..10, bench-observer-11).
- Configuration: no knob in the benchmark harness (`grep -i worker benchmark/config.sh` finds only the
  `worker::network=debug` log filter at `:347` and a UDP port comment at `:526`; no `num_workers` in
  `benchmark/*.sh`). The committee file read by `devnet-network-config.py:409` has `num_workers` with default 1.
  The run's genesis copy `genesis/validators/benchNN.yaml:9` has a `workers:` list; I did not count its entries.
- No gauge such as `tn_*worker_count` exists in the snapshot (grep for num_workers/workers_total/worker_count/worker_id
  in `tn_` names found none).

Smallest addition: record it in the manifest from what the endpoint sampler already fetches, e.g. at the end of a run
count distinct `worker="..."` label values in the last endpoint snapshot per node (offline, no run change); or add
`num_workers` from the committee/genesis files to `manifest.node_startup.<node>`. No new ssh session needed.

## Not determined

- Which time daemon the node image runs (chrony or systemd-timesyncd), so the exact command for measure 1 is unconfirmed.
- Whether `benchmark/node-sampler.sh` and the GCP collector script already read any CPU counter beyond the CSV and
  `metrics.json` keys shown above (I read the saved outputs, not those two scripts).
- The number of entries under `workers:` in `genesis/validators/benchNN.yaml` (the labels say 1; the files were not
  opened beyond the grep).
- Whether the node build under test exposes a worker-count gauge in a newer image: only the bench 7 snapshot was read.
