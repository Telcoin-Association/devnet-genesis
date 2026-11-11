# Bench 6 — names contract (log messages, fields, metrics, YAML keys, manifest keys, CSV columns)

The orchestrator is the only writer. Seeded from the design reports; each row is replaced by the VERBATIM name from the owning
unit's hand-back once it lands (column "landed"). Harness report code (H7), the arm tool (H5) and the analysis units read names
from here, never from the design text.

## Node switches (`parameters.yaml`, top-level; default = bench-5 behaviour)
| key | type | default | arm value | topic | landed (unit, sha) |
|---|---|---|---|---|---|
| `quorum_exec_block` | bool | false | true | quorum-exec-block | |
| `quorum_exec_block_starved_rounds` | u32 | 0 | 0 (rule on every header) / 4 (own tip by default, the rule for K rounds after an own header is cancelled uncertified, K doubling) | quorum-exec-block (added 2026-11-10 after I-4) | |
| `vote_queue_fix` | bool | false | true | voter-lock | |
| `mdbx_random_advice` | bool | false | true | mdbx-advice | |
| `sealed_tx_keep` | bool | false | true | sealed-keep | |
| `digest_dedupe` | bool | false | true | digest-dedupe | |
| `recovery_threads` | u16 | 0 | 3 | recovery-pool | |
| `epoch_close_task_drain` | bool | false | true | tracker-drain | |
| `epoch_record_state_check` | bool | false | true | tracker-drain | |
| `parent_grace` | duration | 0ms | 150ms / 100ms | parent-grace | |
| `rpc_admission_backlog_outputs` | usize | 0 | 2 | inflight-bound | |
| `pipelined_persist` | bool | false | true | pipelined-persist (may be absent from the image) | |

## Node log lines and metrics (design names; to be confirmed by hand-backs)
| topic | name | kind | landed (unit, sha, verbatim) |
|---|---|---|---|
| switches | message `node switches`, level info, target `node::switches`, logged once at node start AFTER `parameters.yaml` is loaded; one field per switch named exactly as its YAML key, in the table order above, values as YAML scalars (`true`/`false`, integers, durations like `150ms`, `0ms`); a key the image does not know is simply absent. Parsers take `key=value` tokens after the message text. | log | |
| switches | `tn_node_switch{name}` | gauge | |
| quorum-exec-block | `header proposed` + `exec_block`, `exec_tip`, `exec_basis` (`quorum`/`tip`/`floor`) | log fields | |
| quorum-exec-block | `tn_primary_parent_exec_block_mismatch_total` (optional) | counter | |
| voter-lock | `VoteStage::PreLockWait`, outcome `superseded`, `prelock_wait_ms` on `vote path timing`; `SupersededRequest` | stage/log/error | |
| voter-lock / tracker-drain | `tn_primary_epoch_entry_rounds_behind` | gauge | |
| mdbx-advice | `tn_reth_mdbx_random_advice_bytes`, `tn_reth_mdbx_used_bytes` | gauges | |
| mdbx-advice | message `persisted output` (existing line) gains, as deltas over that one persist: `page_newly`, `page_cow`, `page_spill`, `page_unspill`, `page_prefault`, `page_wops`, `page_msync` (libmdbx `page_ops` counters) and `proc_write_bytes` (`/proc/self/io` `write_bytes`). Amplification = device write bytes ÷ ((`page_newly` + `page_cow`) × 4096). FROZEN by the orchestrator 2026-11-11: U3 emits exactly these names; H7b and the analysis units parse them. | log fields | |
| mdbx-advice | `tn_reth_mdbx_page_ops_total{op}` with `op` ∈ `newly`, `cow`, `spill`, `unspill`, `prefault`, `wops`, `msync` (FROZEN) | counter | |
| sealed-keep | (per hand-back) | | |
| digest-dedupe | `tn_worker_duplicate_digest_suppressed_total`; proposer-side counter; `skipping invalid transaction` + `sender` | counter/log | |
| recovery-pool | `signers recovered` + `pool=dedicated|global` | log field | |
| tracker-drain | backlog outputs, detect lag, drain seconds, entry lag gauges; `epoch_record_vote_skipped_total{reason}` | gauges/counter | |
| parent-grace | `parent_grace_wait_seconds`, `parent_grace_total{outcome}`, `late_parents_total{origin}` | histogram/counters | |
| inflight-bound | `tn_reth_rpc_admission_refused_total`, `tn_node_execution_backlog_outputs`; refusal text "txpool is full" | counter/gauge | |
| bench6-obs | `tn_engine_recover_seconds`, `tn_engine_evm_seconds`, `tn_engine_root_seconds`, `tn_engine_finish_seconds` on `SUB_MS_SECONDS_BUCKETS` = 0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0 (per consensus OUTPUT, not per tx: per-tx cost = `_sum / executed_transactions_total`; quantiles between 1 and 5 ms are coarse). `tn_engine_execution_duration_seconds` and `tn_engine_persist_duration_seconds` stay on the default set. | buckets | U8 f3d34932e |
| bench6-obs (U10) | `first_received`, `oldest_requeue_wait_ms` | log | |
| pipelined-persist | metrics `tn_engine_unpersisted_outputs`, `tn_engine_built_height`, `tn_engine_persist_wait_seconds`, `tn_engine_commit_interval_seconds`, `tn_engine_close_barrier_holds_total`; `output executed` gains `persist_wait_ms`, `seed_ms`, `pipelined`; new messages "pipelined persist failed - rolling back unpersisted outputs", "pinning the output overlay failed - next output waits for the commit" (I-5 design; to be confirmed by U12b) | metrics/log | |

## Harness names (FROZEN by H0, 2026-11-11; the files are the source of truth, this is the index)
- Knobs (`benchmark/config.sh`): `BENCH_NODE_BOOT_IMAGE` (default `projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105`;
  a `/family/` value is refused), `BENCH_NODE_EVICT_MDBX` (0), `BENCH_PERSIST_SAMPLER` (0), `BENCH_NODE_READ_AHEAD_KB` (empty),
  `BENCH_ARM_FILE` (empty; a `*.arm` file; refuses the two host knobs beside it), `BENCH_TAIL_SCAN_SECS` (0),
  `BENCH_LIGHT_START_DELAY_SECS` (default = `BENCH_START_DELAY_SECS`, 300; run 2 sets 150), `BENCH_NODE_SWITCH_KEYS` (the 12 rows of the
  tsv as `<type>:<key>`, appended to `BENCH_NODE_PARAM_KEYS`).
- `benchmark/arms/switches.tsv` (key, type, default, arm_values, topic, optional) and the arm-file format `benchmark/arms/README.md`
  (`name`, `param <key> <value>`, `host evict-mdbx`, `host read-ahead-kb <n>`; the file is the FULL state; unknown anything = refuse).
- Persist CSV `results/<run>/persist/<inst>.csv`: header in `benchmark/tools/persist-csv-header.txt` (30-s rows; the four
  `mdbx_dat_*` columns every 300 s). Folio census `persist/<inst>.folios.txt`: `benchmark/tools/folio-census-header.txt`.
- Manifest: `benchmark/arms/MANIFEST-FIELDS.md`. `param_arms[]` keeps `name`, `begin`, `end`, `nodes`, `no_restart`, `failed` and gains
  `via`, `file`, `sha256`, `switches`, `host`, `ready`, `restart_secs`, `guard`, `marks`; an arm's window is `ready` (else `begin`) → `end`.
  `node_startup[inst].host` + `host_steps`; lines `HOST_PROBE <inst> <json>` and `HOST_PROBE_SUMMARY kernel=… image=… ra_kb=… uniform=yes|no …`.
  `blasts[]` gains `kind` (`light`/`load`), `arm`, `phases`, `phases_planned`; `blasters[]` gains `created_at`, `create_secs`, `attempts`,
  `late_secs`; also `blast.tail_scan_secs`, `abort.reason` (`create_failed`, `late_create`) + `abort.node/detail/unsent`, `blast_runs[]`,
  `node_boot_image`, `instances[].source_image`, `archive.remote` {`uri`, `verified_at`, `files`, `bytes`}.
  To add (H1b): `blasts[].pool_at_start` {inst: {`pending`, `queued`}} from `txpool_status` at each blast start.
- make_bundle refuses no unknown manifest key (only backfill/KPI keys); `arm_rows` reads `name`, `begin`, `end`, `nodes`, `failed`.

## Generator names (blaster JSON, schema id `tn-blast/v2`, all additive and `serde(default)`)
### H9a (landed in the working tree of tn-transaction-generator, uncommitted; covers warm-up and mixed sender tasks only, not the preamble)
- `series.send_per_second_columns` = `["s","submitted","accepted","resent","resigned","rpc_errors","blocked_senders","inflight"]`;
  `series.send_per_second_t0_unix` (warm-up start, Unix s; 0 if no warm-up); `series.send_per_second` = one dense row per second
  from the warm-up start to the cool-down end. `s` seconds since t0; `submitted` distinct txs first attempted; `accepted` txs
  acknowledged; `resent` send calls repeating bytes already sent (transient, `other`, gap-repair); `resigned` re-signs after
  `nonce_low` or `underpriced`/`fee_cap`; `rpc_errors` calls that returned any error class (`known` included);
  `blocked_senders` gauge (senders with next_nonce − landed nonce ≥ window); `inflight` gauge (Σ max(next_nonce − landed nonce, 0)).
  Send calls in a second = `submitted + resent + resigned`.
- `senders.blocked` = `{total_ms, p50, p95, max, per_sender_ms[], by_phase:{warmup, mixed, cooldown}}` (ms; `per_sender_ms` in
  sender index order; p50/p95 nearest-rank over `per_sender_ms`; a wait counts in the phase it began in).
- `nodes[].resends` and `totals.resends` = `{transient, other, gap_episodes, gap_txs, resign_nonce, resign_fee, dropped}`;
  `transient + other + gap_txs` = Σ `resent`; `resign_nonce + resign_fee` = Σ `resigned`.
- Send path proven unchanged by `blast::sender::tests::send_path_matches_the_golden` (golden
  `src/blast/testdata/send-path-golden.json`, sha256 a52c3022cda7627f097bc017a6808a266f0068cc35217e67c3fa3ed268a359f3).
### H9b (pending hand-back)
(`--tail-scan-secs`, `run.tail_scan`, `late` on landings rows, unlanded count after the tail, gap resends split by answer,
stalled-sender columns, per-transaction unlanded export, finer tail histogram, `bench/aggregate.py` merge)
