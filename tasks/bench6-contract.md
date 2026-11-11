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

All twelve switch fields LANDED: U0a, integration commits 3696d49f3..5b9f13b25 (2026-11-11); `Parameters::switches()` + `SwitchValue` (`gauge()`: bool 0/1, count, duration in ms); `tn_types::ExecutionBacklog` + `AdmissionGate` (closes at backlog ≥ K, reopens below K−1: at K = 2 only at 0).

## Node log lines and metrics (design names; to be confirmed by hand-backs)
| topic | name | kind | landed (unit, sha, verbatim) |
|---|---|---|---|
| switches | message `node switches`, level info, target `node::switches`, logged once at node start AFTER `parameters.yaml` is loaded; one field per switch named exactly as its YAML key, in the table order above, values as YAML scalars (`true`/`false`, integers, durations in humantime form: `150ms`, and `0s` for zero — compare durations BY VALUE, never as strings); a key the image does not know is simply absent. A switch at its default is NOT written to `parameters.yaml` (the arm tool must add an absent key), but the line always lists every switch. Parsers take `key=value` tokens after the message text. | log | |
| switches | `tn_node_switch{name="<yaml key>"}` = bool 0/1, counts as is, durations in MILLISECONDS; rendered default line: `node switches quorum_exec_block=false quorum_exec_block_starved_rounds=0 vote_queue_fix=false mdbx_random_advice=false sealed_tx_keep=false digest_dedupe=false recovery_threads=0 epoch_close_task_drain=false epoch_record_state_check=false parent_grace=0s rpc_admission_backlog_outputs=0 pipelined_persist=false` (logged in `EpochManager::new`) | gauge/log | U0c 644569519 |
| quorum-exec-block | target `consensus::metrics`, message `header proposed` (unchanged) gains `exec_block`, `exec_tip`, `exec_basis` = `tip` \| `quorum` \| `floor`, `exec_policy` = `off` \| `always` \| `tip` \| `starved`. Constants: floor N = 8 ring entries; K doubles up to 128. Under `always`, `exec_basis=floor` is the steady state at every load; under the adaptive policy lag is 0 in step. No new metric. | log fields | U1 e823da217 |
| quorum-exec-block | (`tn_primary_parent_exec_block_mismatch_total` was optional and is NOT built) | — | — |
| voter-lock | stage label `prelock_wait` (`VoteStage::PreLockWait`, the FIRST stage: the other stages' indexes shift by one) in `tn_primary_vote_stage_seconds{stage}` and `tn_primary_vote_timeouts_total{stage}`; outcome `superseded`; field `prelock_wait_ms` on the `vote path timing` line (target `primary::network`, right after `outcome`, 0 with the switch off); refusal `PrimaryNetworkError::SupersededRequest {epoch, round, newest_epoch, newest_round}`, recoverable, no penalty, wire text "Vote request for epoch {e} round {r} superseded by a newer request from the same author for epoch {ne} round {nr}". | stage/log/error | U2 c56b33c0a |
| tracker-drain (gauge) | `tn_primary_epoch_entry_rounds_behind`: the highest round of verified gossip certificates seen while execution is one epoch behind, since this epoch's handler was built (0 at start; a demotion freezes it at 41). Read with `max_over_time`. The admission-bound arm aborts at ≥ 30. | gauge | U2 12bb5bb45 |
| mdbx-advice | `tn_reth_mdbx_random_advice_bytes`, `tn_reth_mdbx_used_bytes` | gauges | |
| mdbx-advice | message `persisted output` (existing line) gains, as deltas over that one persist: `page_newly`, `page_cow`, `page_spill`, `page_unspill`, `page_prefault`, `page_wops`, `page_msync` (libmdbx `page_ops` counters) and `proc_write_bytes` (`/proc/self/io` `write_bytes`). Amplification = device write bytes ÷ ((`page_newly` + `page_cow`) × 4096). Also on the same line, as current values (not deltas): `mdbx_used_bytes` (the database's used size) and `mdbx_advised_bytes` (bytes of `mdbx.dat` mappings carrying the random-access advice; 0 when the switch is off), so the log alone shows whether the advised range covers the used range. Added after the local probe run (U3 emits each one only if it is readable without a vendored edit and in microseconds; its hand-back says which landed): `mdbx_last_pgno` (current), `freelist_pages`, `gc_entries`, `gc_large_pages`, `prefault_wchar_bytes`, optional `mdbx_readahead_enabled`. Prefault on ⇔ Δ`page_prefault` ≈ Δ`mdbx_last_pgno`. FROZEN by the orchestrator 2026-11-11: U3 emits exactly these names; H7b and the analysis units parse them. | log fields | |
| mdbx-advice | `tn_reth_mdbx_page_ops_total{op}` with `op` ∈ `newly`, `cow`, `spill`, `unspill`, `prefault`, `wops`, `msync` (FROZEN) | counter | |
| sealed-keep (pool side) | gauge `tn_reth_sealed_txs_marked`; counters `tn_reth_sealed_txs_cleared_executed_total`, `tn_reth_sealed_txs_cleared_repooled_total`, `tn_reth_sealed_txs_dropped_evicted_total`, `tn_reth_sealed_txs_cleared_lag_total`, `tn_reth_sealed_txs_late_marks_refused_total`; warnings (target `txpool`) `sealed transaction marks dropped after canonical state broadcast lag` (`marks`), `sealed transaction mark sweep failed; retrying after the next interval` (`error`). Marks clear on execution of the batch's digest, on re-pool, on eviction (swept ≤ once a second) and on a broadcast lag. API note: `tasks/bench6/briefs/u6a-api.md`. | gauge/counters/log | U6a da24d6780 |
| sealed-keep (builder side, U6b) | (per hand-back) | | |
| digest-dedupe (worker) | counter `tn_worker_duplicate_digest_suppressed_total` (label `worker`); log target `consensus::metrics`, message `batch digest already reported`, fields `worker_id`, `digest`, `num_txs`. "Already reported" = the digest was reported successfully by this worker instance AND still has its `OurNodeBatchesCache` row. | counter/log | U7 93e9d7c21 |
| digest-dedupe (proposer, U10; `sender` field, U3) | proposer-side counter; `skipping invalid transaction` + `sender` | counter/log | |
| recovery-pool | `signers recovered` (debug, target `engine`) fields `consensus_number txs recover_ms pool`, `pool` last and bare: `pool=dedicated` \| `pool=global`; on the dedicated pool `recover_ms` includes the wait for a pool thread. Warning `signer recovery pool failed to build - recovering on the global pool` (field `threads`). Threads `tn-recover-{i}`; the pool is process-wide and built lazily on the first non-empty output. `tn_engine::run_on_recovery_pool(threads, closure)` for the bench. No new metric. | log field | U4a 4a9e1c014 |
| tracker-drain | gauges (set once per live boundary close, no switch) `tn_node_epoch_close_backlog_outputs` (closing output's number minus the engine's last executed output; counts the closing output itself), `tn_node_epoch_close_detect_lag_seconds`, `tn_node_epoch_close_drain_seconds`; counters `tn_node_epoch_record_vote_skipped_total{reason}` with `certified_before_close` \| `not_in_committee`, `tn_node_epoch_record_state_check_skipped_total`; log (target `epoch-manager`) info `epoch close drained` (`epoch`, `closing_number`, `backlog_outputs`, `detect_lag_ms`, `drain_ms`), error `stored epoch record's final state is not this node's closing block; halting`, warn `no executed block to compare with the stored epoch record's final state; check skipped`; (target `tn::tasks`) info `Epoch Task Manager: task tracking finished` (`tracked`, `reaped`, `running`). The bench-5 error to count stays `Failed to track spawned task`. No entry-lag gauge here (it is `tn_primary_epoch_entry_rounds_behind`). | gauges/counters/log | U5 9277bf947..584f86a83 |
| parent-grace | histogram `tn_primary_parent_grace_wait_seconds` (one sample per armed grace); counter `tn_primary_parent_grace_total{outcome}` with `complete` \| `expired` \| `preempted`; counter `tn_primary_late_parents_total{origin}` with `own_round_behind` \| `older_round` (static labels: it cannot say whose certificate was late); `header proposed` gains `grace_ms` (0 when no grace was armed; the line already carries `num_parents`); debug lines `parent grace armed` (`parent_round`, `parents`, `missing`, `grace_ms`) and `parent grace ended` (`parent_round`, `outcome`, `waited_ms`), target `primary::proposer`. G is capped at `max_header_delay`; no grace in the first two rounds of an epoch or without a last own header. | histogram/counters/log | U9 2741f6df0 |
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
- Persist CSV `results/<run>/persist/<inst>.csv`: header in `benchmark/tools/persist-csv-header.txt` (41 columns; 30-s rows; the five
  `mdbx_dat_*` columns every 300 s; the last, `mdbx_dat_resident_past_used_pages`, was added after the first freeze and is
  blank on an image without the `tn_reth_mdbx_used_bytes` gauge). Sampler env `PERSIST_*` (see `node-persist-sampler.sh`);
  metrics URL default `http://127.0.0.1:<METRICS_PORT from /etc/telcoin/.node-meta, else 9101>/metrics`. Folio census `persist/<inst>.folios.txt`: `benchmark/tools/folio-census-header.txt`.
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
### H9b (landed; generator commit d3be21a on local main, not pushed)
- CLI `--tail-scan-secs N` (default 0 = nothing runs, `run.args` has no `tail_scan_secs` key). After the cool-down the senders stay
  stopped and the scanner books landings for up to N s; ends early when every acknowledged tx landed. `run.phases` keeps four phases;
  `run.ended_unix` includes the tail.
- `run.tail_scan` = {`secs`, `start_ms`, `end_ms`, `end_reason` (`elapsed`|`all_landed`|`signal`|`scanner_stopped`|`skipped`|null),
  `boundary_block`, `landed_late`, `by_type`, `unlanded_after`}. `totals.unlanded_own_at_cooldown_end` keeps bench 5's meaning;
  `totals.unlanded_own` and `types.*.unlanded_own` now mean "after the tail" (equal at N = 0).
- `nodes[].resends` / `totals.resends` also carry `gap_txs_ok`, `gap_txs_known`, `gap_txs_err` (sum = `gap_txs`), `gap_checks`
  (= `gap_checks_head_known` + `gap_lookup_failed` + `gap_hole_no_bytes` + `gap_episodes`).
- `series.send_per_second_columns` has 20 columns: the eight above, then `calls`, `retries`, `resent_ok`, `resent_known`,
  `resent_err`, `rpc_err_known`, `rpc_err_other`, `rpc_err_transient`, `rpc_err_nonce_low`, `rpc_err_fee`, `stalled_30s`,
  `stalled_300s`. Identities: `calls = submitted + retries + resigned + resent_ok + resent_known + resent_err`;
  `resent = retries + resent_*`; Σ `rpc_err_*` = `rpc_errors`.
- `latency.hist_seen_tail` and `latency.by_phase.*.hist_seen_tail`: bounds_ms 30000, 60000, 120000, 250000, 290000, 300000, 310000,
  330000, 400000, 600000 (11 counts).
- Landings rows gain `late` (bool; present only when the tail ran).
- New file `unlanded-<label>.ndjson.gz` beside the landings export (harness path `/out/unlanded-${LABEL}.ndjson.gz`): keys `hash`,
  `type`, `node`, `sender`, `nonce`, `phase`, `submit_ms`, `accept_ms`, `resends`, `last_resend_ms`, `last_answer`, `pos`,
  `node_knows`; caps 100,000 rows and 20,000 `eth_getTransactionByHash` lookups (64 at a time, all within 30 s).
- Log lines: `blast: unlanded export written` (`rows`, `unlanded`, `sample`, `lookup_sample`, `node_knows`, `node_unknown`,
  `lookup_failed`), `blast: unlanded export failed`, `blast: tail scan finished` (`secs`, `end`, `boundary_block`, `took_ms`, `pending`).
- `bench/aggregate.py` merges all of it across blasters; old inputs aggregate byte-for-byte as before.
- Harness must (H1b): pass `BENCH_TAIL_SCAN_SECS` as `--tail-scan-secs` (only when non-zero), collect the `unlanded-*` file with the
  landings file, and extend every done-wait deadline by the tail plus up to 30 s of unlanded lookups (they run whenever the landings
  export is on, even at N = 0, before the results are written).
- **H9c rule (generator commit on top of d3be21a, see the ledger line below)**: with the tail scan on, every field that existed
  before it keeps its tail-off value; late blocks and late landings count only under `run.tail_scan`, which also carries
  `blocks_late`, `landed_late_acknowledged` and `hist_land_late` (bounds as `latency.hist_seen_tail`); `unlanded_after` =
  `totals.unlanded_own − landed_late_acknowledged`; `totals.unlanded_own` keeps bench 5's meaning (= `unlanded_own_at_cooldown_end`).
  Only `run.ended_unix` and the cool-down's end move. Proof: `the_tail_scan_changes_no_existing_field` + fixtures
  `bench/fixtures/blast-v2-tail-{off,on}.json`.
- Not taken: `resends` / `first_resend_ms` on landings rows (would need a shared-ledger write on the per-tx resend path); `senders.stalls`.

## Analysis outputs (H7b, landed 2026-11-11)
- `benchmark/tools/arms-summary.py [--run-dir D] [--self-check] [--results-root R] [--out-dir O] [--prefiltered P] [--cache-dir C]
  [--types T] [--drift-axis {chain-mtx,wall-min}] [--no-stages] [--jobs N]` → `<run>/analysis/arms.{md,json}`; exit 0 written,
  1 bad input, 2 no row, 3 self-check mismatch. Row ids `<arm>/<type>` (`L` 8×16, `M4` 600×4, `M16` 600×16 with planned mixed ≥ 400 s,
  `M16s` shorter, `I` idle mark); a run without `param_arms` is one arm `implicit`.
- `arms.json`: top level `tool, run_name, generated_utc, drift_axis, notes, drift, arm_list, summary_rows, log_files`;
  `summary_rows[]` keys include `row_id, arm_name, blast_type, utc_from, utc_to, seconds, switch_set, chain_txps, landed_txps,
  land_p50_s, land_p95_s, gen_seen_p50_s, gen_seen_p95_s, engine_by_node, execute_us_tx, persist_us_tx, commit_us_tx,
  commit_ms_output, task_us_tx, txs_per_output, amp_fleet_median, rr_vma_min, cert_by_validator, cert_min_pct, vote_lock_p95_ms,
  behind_per_header_max, tracker_errors, landings_ge300, resends_by_cause, resends_total, tail_landed_late, tail_unlanded_after,
  late_secs_max, gen_silent_max_s, stage_seen_p50_s, stages, commit_us_tx_corrected, drift_moved_pct_abs, verdict[]`.
  Missing inputs are the string `n/a (missing: <what>)`. Every parsed field name sits in the tool's `F` table.
- Not computed (no input exists yet): duplicate digests, parents per header, grace `expired`, the `finish` overlap, a used-size
  column (to add from `mdbx_used_bytes` on the `persisted output` line once U3 lands: small H7b follow-up).
- stage-latency window names for bench-6 blasts: `[<arm>/]<kind><senders>x<window>` (e.g. `v/load600x16`); `--only GLOB`.
