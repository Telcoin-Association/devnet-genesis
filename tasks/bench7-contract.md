# Bench 7 - node build contract: log lines, fields, metrics, switches and test hooks

Build: telcoin-network detached at `a11f14b1b` = upstream main `45dce8947` + 95 commits. Every name below was read from the source at
`a11f14b1b` (`path:line` are lines of that tree). Where a unit's notes differ from the code, the code is used and the difference is
in section 7. Plain ASCII; "main" means `45dce8947`.

Metric naming: the code registers `tn_<scope>.<name>` (a dot); the Prometheus exporter turns every `.` into `_`
(`crates/tn-metrics/src/lib.rs:19-22`, `crates/tn-metrics/src/recorder.rs:251`; the registered `tn_epoch.runs_total` is
`tn_epoch_runs_total` in `docs/src/getting-started/observability-listeners.md:117`). A name registered with an underscore
(`tn_node_switch`) is unchanged. Counters get no extra suffix beyond what the code names (`_total` is part of the registered name);
histograms render `_bucket{le=..}`, `_sum`, `_count`. Both forms are given for every metric.

## 1. Switches (`runtime_switches!`, `crates/config/src/node.rs:772-783`, list order)

All seven are top-level keys of `parameters.yaml`; YAML key = field name; read once at start; a switch at its default is NOT written
by the node (`skip_serializing_if = "Parameters::switch_at_default"`, node.rs:725), so the arm tool must ADD an absent key; the
`node switches` line always lists all seven. Default = main's behaviour for every switch.

| # | YAML key | type | default | what turns on | unit / topic / issue | read at (`path:line`) | field decl |
|---|---|---|---|---|---|---|---|
| 1 | `quorum_exec_block` | bool | false | headers name the execution block a 2f+1-weight quorum of parents reached (capped at own tip, floor 8 ring entries, never older than the epoch's opening block) instead of the node's own newest block | PT-3a (+PT-3c, PT-3v), `quorum-exec-block`, #1804 | `crates/consensus/primary/src/proposer.rs:359` | node.rs:341 |
| 2 | `quorum_exec_block_starved_rounds` | u32 (count) | 0 | with #1 on: 0 = rule on every header; K>0 = own tip by default, the rule only for K header-windows after an own header was cancelled uncertified, K doubling (K above 128 lowered to 128; K>0 with #1 off has no effect; both warn) | PT-3a, `quorum-exec-block`, #1804 | `proposer.rs:360` | node.rs:354 |
| 3 | `epoch_record_recertify` | bool | false | re-vote one older uncertified own epoch record at each close and at startup (round-robin over the last 16 epochs) and keep verified epoch-vote signatures across vote rounds | E4 (+E4-FU), `epoch-record-collector-hardening`, #1850 | `crates/node/src/manager/node.rs:1301`; `crates/node/src/manager/epoch_votes.rs:687` | node.rs:384 |
| 4 | `epoch_record_collect_past_uncertified` | bool | false | record collector and startup sync walk past an epoch this node holds as its own uncertified record; skipped epochs become a gap retried (<= 16 gaps, once per 5 s, 5 s deadline) | E3 (+E3-FU), #1850 | `crates/state-sync/src/epoch.rs:117` | node.rs:402 |
| 5 | `epoch_record_conflict_halt` | bool | false | stop the node when a record certified by a super-quorum of the FULL previous committee differs from this node's own record; also decides the re-certify round's stop | E3 (+E3-FU, E4-FU), #1850 | `crates/state-sync/src/epoch.rs:118`; `crates/node/src/manager/epoch_votes.rs:688` | node.rs:428 |
| 6 | `vote_queue_fix` | bool | false | voter refuses a request older than the newest from the same author at once (recoverable `SupersededRequest`) and does its bounded execution wait BEFORE the per-author lock | PT-2B (+PT-2C), `voter-lock`, #1804 | `crates/consensus/primary/src/network/handler.rs:1046`, `:1138`, `:1587`; validation `crates/config/src/consensus.rs:550` | node.rs:444 |
| 7 | `digest_order_hold` | bool | false | proposer leaves queued every digest of a worker lane named in a tracked older own header that the new header's parents do not prove to be on its own chain | HD-2a/HD-2b, `digest-order-hold`, #1807 | `proposer.rs:409` | node.rs:465 |

Types in the `SwitchValue` family: `bool`, `u16`, `u32`, `u64`, `usize` (count), `Duration` (node.rs:790-859); none of the seven is a Duration.

**`node switches` log line** (`crates/config/src/node.rs:761-767`, macro `log_switches`; called once per process from
`EpochManager::new`, `crates/node/src/manager/node.rs:772`, after `parameters.yaml` is loaded): level INFO, target `node::switches`,
message `node switches`, then one field per switch named exactly as its YAML key, in the table order above, each rendered with
`%` (Display): bool `true`/`false`, count as decimal, duration humantime (`150ms`, `0s`; none now). Rendered line at the defaults
(pinned by `node_switches_line_renders_yaml_tokens`, node.rs:1657):
`node switches quorum_exec_block=false quorum_exec_block_starved_rounds=0 epoch_record_recertify=false epoch_record_collect_past_uncertified=false epoch_record_conflict_halt=false vote_queue_fix=false digest_order_hold=false`
A key the image does not know is simply absent from the line; a mistyped key in `parameters.yaml` is ignored without an error (read the line, not the file).

**`tn_node_switch` gauge** (`crates/node/src/metrics.rs:13` `NODE_SWITCH_GAUGE = "tn_node_switch"`, set in `record_node_switches`,
metrics.rs:84-93, called at `crates/node/src/manager/node.rs:773`): registered name `tn_node_switch`, Prometheus name `tn_node_switch`
(no dot), gauge, label `name` = the YAML key (7 series), set once at start. Value (`SwitchValue::gauge`, node.rs:802): bool 0/1;
count as is (`quorum_exec_block_starved_rounds=4` exports 4); duration in MILLISECONDS.

## 2. Log lines, new or changed vs main

Field order is the source order; `(new)` = field not on main's line; `(%)` Display, `(?)` Debug as in source. A line with `{x}` in its message
is a format string: the text is the literal source text. Line numbers are the macro's first line. Fields marked `*` are on the line only when the
named target is at that level (debug lines need the target enabled).

### 2.1 Switches and observability
| message (verbatim) | level | target | fields in order | topic | path:line | when |
|---|---|---|---|---|---|---|
| `node switches` | info | `node::switches` | the 7 switch keys (section 1), each `%` | bench6-switches | crates/config/src/node.rs:762 (called `crates/node/src/manager/node.rs:772`) | once per process at start, after parameters.yaml is loaded |
| `header proposed` | info | `consensus::metrics` | `round`, `epoch`, `num_batches`, `num_parents`, `created_at_ms`, `reason`, `digests`(%), `oldest_digest_wait_ms`, `requeued`, `oldest_requeue_wait_ms` (new), `pending_before`, `exec_block` (new), `exec_tip` (new), `exec_basis` (new), `exec_policy` (new), `own_parent` (new), `held` (new), `held_lanes` (new), `blockers` (new) | bench6-obs; quorum-exec-block; digest-order-hold | crates/consensus/primary/src/proposer.rs:525 | one per own header built. `oldest_requeue_wait_ms` = longest wait from first receipt among the header's re-queued digests, 0 if none; `oldest_digest_wait_ms` keeps main's meaning (since last queueing) |

### 2.2 Voter queue (`vote_queue_fix`, #1804)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `vote path timing` | debug* | `primary::network` | `author`(%), `round`, `epoch`, `outcome`, `prelock_wait_ms` (new, right after `outcome`; 0 with the switch off), `lock_ms`, `validate_ms`, `exec_wait_ms`, `parents_ms`, `lead_ms`, `batches_ms`, `store_ms`, `persist_ms`, `total_ms` | crates/consensus/primary/src/network/handler.rs:984 | once per vote request. `outcome` values: `created`, `recast`, `missing_parents`, `deferred`, `too_new`, `behind`, `superseded` (new), `rejected`, `timeout`, `error` (`VoteOutcome::as_str`, handler.rs:2552) |
| (refusal, not a log line) `Vote request for epoch {epoch} round {round} superseded by a newer request from the same author for epoch {newest_epoch} round {newest_round}` | - | - | `PrimaryNetworkError::SupersededRequest {epoch, round, newest_epoch, newest_round}`; recoverable, no penalty (wire `RecoverableError`) | crates/consensus/primary/src/error/network.rs (variant `SupersededRequest`), network/message.rs | with `vote_queue_fix` on, a request older than the newest from the same author |

### 2.3 Closing-block check (E1, #1851; no switch, always on)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `epoch record final_state is not the block where the epoch-closing calls ran, stopping the node` | error | `epoch-manager` | `epoch`, `path`, `check`, `reason`, `certified`, `block_number`, `block_hash`(%), `beacon_root`(?), `nonce_epoch`, `extra_data`(%), `seed`(?), `final_consensus_number`, `final_consensus_hash`(%) | crates/node/src/manager/node/close_epoch.rs:1805 | the check fails; the node stops (section 4). `path` = `built`\|`rederived`\|`stored`\|`entry`; `check` = `no_block`\|`beacon_root`\|`nonce_epoch`\|`extra_data_length`\|`extra_data_seed`; `reason` = `save, vote on or publish a record that commits another block` (built, rederived) or `run on a chain no epoch record attests` (stored, entry) |
| `epoch record published` | info | `epoch-manager` | `epoch`, `final_state_number`, `final_state_hash`(%), `final_consensus_number`, `final_consensus_hash`(%), `digest`(%), `branch` | close_epoch.rs:1877 (called :743 with `stored_matched`\|`stored_restored`, :845 with `built`) | when this node publishes its own record on `epoch_record_watch` |

### 2.4 Epoch-record collector hardening (E2, E3, E4, E5a; #1850)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `retrieved cert for epoch {epoch}: {epoch_hash} from a peer` | info | `epoch-manager` | `peer`(%) (new), `signers` (new) | crates/state-sync/src/epoch.rs:746 | the collector / startup sync stored a certified record from a peer |
| `retrieved cert for epoch {}/{new_epoch_hash} from a peer` | info | `epoch-manager` | `peer`(%) (new), `signers` (new) | crates/node/src/manager/epoch_votes.rs:430 | a vote round's recovery stored the network's certificate for the same digest |
| `got an invalid epoch record, epoch {epoch}` | error | `epoch-manager` | `epoch_matches`(?), `parents_match`(?), `committee_valid`(?), `cert_valid`(?), `peer`(%) (new) | epoch.rs:760 | a peer's record fails validation |
| `epoch record collector walking past an uncertified epoch` | info | `epoch-manager` | `epoch`, `gaps` | epoch.rs:204 | `epoch_record_collect_past_uncertified` on: a gap opened (counts `epoch_record_gap_walks_total`) |
| `no peer returned the certified record of an uncertified epoch walked past: {err}` | debug* | `epoch-manager` | `epoch` | epoch.rs:846 | gap retry found no peer with the record |
| `epoch record conflict halt: this node's stored record of epoch {epoch} differs from a record certified by {signers} of the {committee} members of the committee the record before it names; this node stops; do not delete its chain data before the cause is known` (message = `{text}`) | error | `epoch-manager` | `epoch`, `stored`(%), `offered`(%), `peer`(%), `signers`, `committee`, `signer_ids`(%), `offered_epoch`, `offered_parent`(%), `offered_final_number`, `offered_final_hash`(%), `halt_threshold`, `conflict_halt` | epoch.rs:276 (text built :262-272) | conflict with certificate signers >= `halt_threshold` AND `epoch_record_conflict_halt` on; returns Err (collector ends / startup fails) |
| `epoch record conflict: this node's stored record of epoch {epoch} differs from a record certified by {signers} of the {committee} members of the committee the record before it names; this node keeps its own record` | error | `epoch-manager` | same 13 fields | epoch.rs:276 | any other conflict (switch off, or below threshold); node keeps running, asks again |
| `epoch vote round ended without a local quorum; the record is already certified` | info | `epoch-manager` | `epoch`, `digest`(%), `signers`, `cert_signers`, `timeouts`, `missing`(%) | epoch_votes.rs:327 | a vote round fell short but a certificate for the digest is already stored (replaces the quorum error in that case) |
| `epoch record certified from kept votes` | info | `epoch-manager` | `epoch`, `digest`(%), `signers` | epoch_votes.rs:506 | `epoch_record_recertify` on: kept signatures reached a quorum after a short round |
| `re-arming epoch vote rounds to re-certify older epoch records` | info | `epoch-manager` | `epoch` | epoch_votes.rs:844 | startup, `epoch_record_recertify` on and an older uncertified record is held |
| `epoch record re-certify round` | info | `epoch-manager` | `epoch`, `digest`(%), `retained`, `needed` | epoch_votes.rs:915 | a re-certify pick at a close |
| `own epoch record differs from a certified record in a re-certify round` | error | `epoch-manager` | `epoch`, `digest`(%), `certified_digest`(%), `signers`, `committee`, `needed`, `peer`(%), `halt`, `stop` | epoch_votes.rs:974 | a re-certify round fetched a different certified record; the node stops iff `stop=true` (= `halt` and `signers >= needed`); no `halt:` phrase on this line |
| `failed to reach quorum on epoch close for {epoch_hash} {epoch_rec:?}` (text on main; now only when the record is not already certified) | error | `epoch-manager` | `signers`, `timeouts`, `missing`(%) | epoch_votes.rs:342 | vote round ended short and no certificate is held |
| `Failed to retrieve an epoch record for epoch {}- We have a missing epoch certificate, if this is not local then sync will be compromised!` (text on main; alarm now gated by `missing_cert_alarm && !certified`) | error | `epoch-manager` | - | epoch_votes.rs:529 | recovery found no record and none certified from kept votes |
| `test hook: withholding own epoch vote` | info | `epoch-manager` | `epoch`, `round` | epoch_votes.rs:1304 | `TN_TEST_WITHHOLD_EPOCH_VOTE` hook withheld a round |

### 2.5 Epoch-loop output drop (XF-1, XF-1b; no switch)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `skipping already-forwarded consensus output` | warn | `epoch-manager` | `number`, `last_forwarded`, `digest`(?) (new), `path` (new) = `"live"` | crates/node/src/manager/node/run_epoch.rs:834 | live forward meets an output already forwarded |
| `skipping already-forwarded consensus output` | warn | `epoch-manager` | `number`, `last_forwarded`, `digest`(?), `path` = `"leftover_queue"` (all new on this path) | crates/node/src/manager/node/close_epoch.rs:554 | leftover drain phase 1 meets one (also counts `tn_node.leftover_outputs_skipped_total`) |
| `leftover consensus output does not follow the last output forwarded to the engine: stopping the node before the engine executes past the gap` | error | `epoch-manager` | `number`, `last_forwarded` | close_epoch.rs:566 | drain phase 1 sees a gap; returns Err (section 4); counts `tn_node.leftover_output_gaps_total` |

### 2.6 Vote fix: `quorum_exec_block` (PT-3a, PT-3c; #1804)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `quorum_exec_block_starved_rounds has no effect while quorum_exec_block is off` or `quorum_exec_block_starved_rounds is above its bound; the bound is used` (message = `{warning}`) | warn | `primary::proposer` | `quorum_exec_block`, `quorum_exec_block_starved_rounds`, `bound` (= 128) | proposer.rs:365 (texts `starved_rounds_warning`, :2145) | once per proposer start (per epoch) on those values |
| `header proposed` | info | `consensus::metrics` | see 2.1; values: `exec_block` = number of the named block, `exec_tip` = own tip number; `exec_basis` = `tip`\|`quorum`\|`floor`; `exec_policy` = `off`\|`always`\|`tip`\|`starved` | proposer.rs:525 | `off` with the switch off (basis then `tip`); `always` = switch on, starved_rounds 0; `tip`/`starved` = adaptive (K>0) outside / inside a window. Constants: floor = 8 ring entries (`QUORUM_EXEC_BLOCK_FLOOR_ENTRIES`, :1958); window cap 128 (`QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`, :1986); reset streak 64 (`QUORUM_EXEC_BLOCK_RESET_STREAK`) |

### 2.7 Order hold (`digest_order_hold`, HD-1, HD-2b, HD-4a; #1807)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `header proposed` | info | `consensus::metrics` | `own_parent` (bool: parents cite the tracked own header of round-1), `held` (digests left queued in held lanes), `held_lanes` (count), `blockers` (count of tracked digest-carrying headers not proven ancestors) - all 4 new, last on the line; `held`/`held_lanes`/`blockers` are 0 with the switch off | proposer.rs:525 | every header |
| `digests resent` | info | `consensus::metrics` | `count`, `from_round`, `round`, `cause` (`canceled`\|`committed`), `out_of_order` (new) | proposer.rs:1172 | a non-empty re-queue; `out_of_order` = digests that returned behind a newer digest of their lane (judged with or without the switch) |
| `digests re-queued out of order under the order hold` | warn | `primary::proposer` | `count`, `from_round`, `round`, `cause`, `out_of_order` | proposer.rs:1185 | switch on AND `out_of_order > 0` (the hold did not cover the lane: GC cut or fault) |
| `proposer stopped` | info | `consensus::metrics` | `epoch`, `round`, `queued_digests`, `proposed_uncommitted`, `uncommitted_digests`, `in_flight_digests` | proposer.rs:1586 | proposer shutdown arm (epoch close) only; always on (no switch) |
| `uncertified own header report dropped` | debug* | `primary::certifier` | `round`, `digest`(%), `reason` (`shutdown`\|`full`\|`unsubscribed`) | crates/consensus/primary/src/certifier.rs:854 | the certifier could not hand a cancelled header's report to the proposer (counts `tn_primary.uncertified_report_dropped_total`) |

### 2.8 Orphan re-pool (HD-3; no switch)
| message | level | target | fields in order | path:line | when |
|---|---|---|---|---|---|
| `Finished processing orphaned batches` | info | `epoch-manager` | `batches`, `processed_batches`, `processed_transactions`, `txs_repooled` (new), `txs_invalid` (new), `txs_already_pooled` (new), `txs_refused_nonce_too_low` (new), `txs_refused_other` (new) | close_epoch.rs:413 | end of the orphan batch re-pool at epoch start |
| `pool refused an orphaned transaction` | debug* | `epoch-manager` | `worker_id`, `error`(?) | close_epoch.rs:349 | per refused transaction (line text on main; refusal now classified) |

### 2.9 Test hooks' lines (only with a `test-utils` build and the variable set; section 5)
| message | level | target | fields | path:line | when |
|---|---|---|---|---|---|
| `test hook: holding this node's own certificates` | warn | `primary::certifier` | `delay_ms`, `stage`, `every` | crates/types/src/test_hooks.rs:416 | once, when `TN_TEST_OWN_CERT_DELAY_*` parsed to a hold |
| `ignoring {var}: not {expected}; own certificates are not held` | warn | `primary::certifier` | `value`(?) | test_hooks.rs:384 | an own-cert variable does not parse |
| `test hook: holding own certificate` | info | `primary::certifier` | `round`, `stage`, `hold_ms` | certifier.rs:871 | each hold |
| `new proposal received during the own certificate hold - aborting proposal...` | debug* | `primary::certifier` | - | certifier.rs:531 | `before_store` hold cancelled by a newer own header |
| `ignoring TN_TEST_WITHHOLD_EPOCH_VOTE: not an epoch number; the node votes as usual` | warn | `epoch-manager` | `value`(?), `err`(%) | test_hooks.rs:497 | bad epoch value |
| `ignoring TN_TEST_WITHHOLD_EPOCH_VOTE_ROUNDS: not a whole number of at least 1; one round is withheld` | warn | `epoch-manager` | `value`(?) | test_hooks.rs:507 | bad rounds value |
| `test hook: withholding own epoch vote` | info | `epoch-manager` | `epoch`, `round` | epoch_votes.rs:1304 | each withheld round |

## 3. Metrics, new or changed vs main

"Registered" is the string in the code; "Prometheus" is what a scrape shows (`.` becomes `_`). Derive-style fields are registered when the
owning struct is built (value 0 from start, switch or no switch); `metrics::counter!` series with labels exist only after first use unless noted.

### 3.1 Switches and observability
| registered | Prometheus | type | labels (values) | topic | path:line | meaning |
|---|---|---|---|---|---|---|
| `tn_node_switch` | `tn_node_switch` | gauge | `name` = the 7 YAML keys of section 1 | bench6-switches | crates/node/src/metrics.rs:13, :84-93 | the arm a node runs; value encoding in section 1 |
| `tn_primary.epoch_entry_rounds_behind` | `tn_primary_epoch_entry_rounds_behind` | gauge | none | bench6-obs | crates/consensus/primary/src/metrics.rs:160 (set :189-210) | highest round of a verified certificate from the epoch after the last executed one, in the newest such epoch (0 at start of a handler built for a later epoch; a mode change keeps it); read with `max_over_time` |
| `tn_primary.digest_wait_seconds` (changed) | `tn_primary_digest_wait_seconds` | histogram | none | bench6-obs | metrics.rs:107 | now measured from a digest's FIRST receipt (survives a re-queue); sample = max(`oldest_digest_wait_ms`, `oldest_requeue_wait_ms`) |
| `tn_engine.recover_seconds`, `tn_engine.evm_seconds`, `tn_engine.root_seconds`, `tn_engine.finish_seconds`, `tn_reth.block_execute_seconds`, `tn_reth.block_signer_recovery_seconds`, `tn_reth.block_finish_seconds`, `tn_reth.block_hashed_state_seconds`, `tn_reth.block_state_root_seconds`, `tn_reth.block_overlay_extend_seconds` (changed: buckets only) | same with `_` (`tn_engine_recover_seconds`, ...) | histogram | none | bench6-obs | crates/tn-metrics/src/recorder.rs:51-62 (list), :234 (applied) | now on `SUB_MS_SECONDS_BUCKETS` = 0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0 (recorder.rs:32); `tn_engine_execution_duration_seconds`, `tn_engine_persist_duration_seconds`, `tn_reth_persist_save_blocks_seconds`, `tn_reth_persist_commit_seconds` keep the default set |

### 3.2 Voter queue (`vote_queue_fix`)
| registered | Prometheus | type | labels (values) | path:line | meaning |
|---|---|---|---|---|---|
| `tn_primary.vote_stage_seconds` (changed) | `tn_primary_vote_stage_seconds` | histogram | `stage` = `prelock_wait` (new, first), `validate`, `exec_wait`, `parents`, `lead_sleep`, `sync_batches`, `vote_store`, `persist`; plus `lock` (the lock-wait series, main) | metrics.rs:361-363 (labels `VoteStage::as_str` :280-291) | time per vote stage; `prelock_wait` = the wait before the per-author lock |
| `tn_primary.vote_timeouts_total` (changed) | `tn_primary_vote_timeouts_total` | counter | `stage` = same 8 values (no `lock`) | metrics.rs:366 | timeouts per stage |
| `tn_primary.vote_outcomes_total` | `tn_primary_vote_outcomes_total` | counter | `outcome` = `created`, `recast`, `missing_parents`, `deferred`, `too_new`, `behind`, `superseded`, `rejected`, `timeout`, `error` (all 10 registered at start) | metrics.rs:369 | one per vote request, same `outcome` as the `vote path timing` line |

### 3.3 Closing-block check and close identity
| registered | Prometheus | type | labels | path:line | meaning |
|---|---|---|---|---|---|
| `tn_epoch.epoch_record_closing_block_check_total` | `tn_epoch_epoch_record_closing_block_check_total` | counter | `result` = `ok`, `no_block`, `beacon_root`, `nonce_epoch`, `extra_data_length`, `extra_data_seed` | crates/node/src/metrics.rs:68 (`ClosingBlockCheck::as_str`, close_epoch.rs:1694-1701) | one per run of the check on the 4 paths (built, rederived, stored, entry); anything but `ok` stops the node |
| `tn_epoch.epoch_close_identity_check_total` | `tn_epoch_epoch_close_identity_check_total` | counter | `result` = `ok`, `mismatch` | metrics.rs:79 (called run_epoch.rs:1015) | close-time base-fee identity (canonical tip + 1 == entered epoch's blockHeight); not counted when the epoch-info read fails |

### 3.4 Epoch-record collector hardening
| registered | Prometheus | type | labels | path:line | meaning |
|---|---|---|---|---|---|
| `tn_state_sync.epoch_records_certified_through` | `tn_state_sync_epoch_records_certified_through` | gauge | none | crates/state-sync/src/metrics.rs:44 (set epoch.rs:992) | highest E with a record and certificate for every epoch 0..=E; -1 when epoch 0 has no certificate |
| `tn_state_sync.epoch_record_gap_walks_total` | `tn_state_sync_epoch_record_gap_walks_total` | counter | none | metrics.rs:50 (epoch.rs:203) | gaps opened by a walk past an own uncertified epoch (switch `epoch_record_collect_past_uncertified`) |
| `tn_state_sync.epoch_record_walk_parent_mismatches_total` | `tn_state_sync_epoch_record_walk_parent_mismatches_total` | counter | none | metrics.rs:55 (epoch.rs:643) | walks that ended on a next record naming another parent |
| `tn_state_sync.epoch_record_conflicts_total` | `tn_state_sync_epoch_record_conflicts_total` | counter | none | metrics.rs:60 | every conflict (halt switch on or off) |
| `tn_state_sync.epoch_record_conflicts_below_halt_threshold_total` | `tn_state_sync_epoch_record_conflicts_below_halt_threshold_total` | counter | none | metrics.rs:67 | conflicts whose signers fall short of a super-quorum of the full committee; total minus this = conflicts that would stop the node with the switch on |
| `tn_node.epoch_record_round_ended_certified_total` | `tn_node_epoch_record_round_ended_certified_total` | counter | none | crates/node/src/manager/epoch_votes.rs:324 | vote rounds that fell short while the record was already certified (series exists after the first short round) |
| `tn_node.epoch_record_round_conflicts_total` | `tn_node_epoch_record_round_conflicts_total` | counter | `round` = `current`, `recertify` | epoch_votes.rs:395 | a round's recovery fetched a different certified record (`RoundKind::label`, :1184-1187) |
| `tn_node.epoch_record_recertify_rounds_total` | `tn_node_epoch_record_recertify_rounds_total` | counter | `result` = `certified`, `short`, `skipped` | epoch_votes.rs:523, :910 | this node's own re-certify picks (switch `epoch_record_recertify`) |
| `tn_node.epoch_record_retained_votes` | `tn_node_epoch_record_retained_votes` | gauge | none | epoch_votes.rs:1166 | signatures kept across rounds (switch on) |
| `tn_node.epoch_record_missing_signers_total` (changed: new label) | `tn_node_epoch_record_missing_signers_total` | counter | `signer`, `round` (new) = `current`, `recertify` | epoch_votes.rs:1283 | members whose vote was missing; main had `signer` only |
| `tn_node.epoch_record_signers` (changed semantics, no new name) | `tn_node_epoch_record_signers` | gauge | none | epoch_votes.rs (`record_epoch_record_signers`) | now set only by rounds of the latest and the previous record, never by re-certify rounds of older records |

### 3.5 Epoch-loop output drop
| registered | Prometheus | type | labels | path:line | meaning |
|---|---|---|---|---|---|
| `tn_node.leftover_outputs_skipped_total` | `tn_node_leftover_outputs_skipped_total` | counter | none | close_epoch.rs:553 | outputs the leftover drain skipped as already forwarded (0 on an honest run) |
| `tn_node.leftover_output_gaps_total` | `tn_node_leftover_output_gaps_total` | counter | none | close_epoch.rs:565 | gaps that stopped the node (0 on an honest run) |

### 3.6 Order hold and certifier
| registered | Prometheus | type | labels | path:line | meaning |
|---|---|---|---|---|---|
| `tn_primary.requeued_out_of_order_total` | `tn_primary_requeued_out_of_order_total` | counter | `cause` = `canceled`, `committed` | crates/consensus/primary/src/metrics.rs:573 | digests re-queued behind a newer digest of their lane (counted with the switch on or off) |
| `tn_primary.requeued_order_unknown_total` | `tn_primary_requeued_order_unknown_total` | counter | `reason` = `unknown_seq`, `stale_resend` | metrics.rs:637 | re-queued digests whose order could not be judged (never counted as out of order) |
| `tn_primary.headers_held_total` | `tn_primary_headers_held_total` | counter | none | metrics.rs:667 (inc proposer.rs:1298) | own headers that left at least one digest queued in a held lane (0 with the switch off) |
| `tn_primary.digests_held` | `tn_primary_digests_held` | gauge | none | metrics.rs:668 (set proposer.rs:1300, 1598) | digests the newest header left queued in held lanes; 0 when nothing is held and when the proposer stops |
| `tn_primary.uncertified_report_dropped_total` | `tn_primary_uncertified_report_dropped_total` | counter | `reason` = `shutdown`, `full`, `unsubscribed` | certifier.rs:861 | cancelled-header reports the certifier could not hand to the proposer |
| `tn_primary.digests_requeued_total{cause}` | `tn_primary_digests_requeued_total` | counter | `cause` = `canceled`, `committed` | main's, unchanged | (listed because the `digests resent` line's `count` feeds it) |

### 3.7 Orphan re-pool
| registered | Prometheus | type | labels | path:line | meaning |
|---|---|---|---|---|---|
| `tn_node.orphan_txs_total` | `tn_node_orphan_txs_total` | counter | `result` = `repooled`, `invalid`, `already_pooled`, `refused_nonce_too_low`, `refused_other` (`OrphanTxResult::label`, close_epoch.rs:187-192) | close_epoch.rs:253 | one per orphaned transaction, recorded per batch |
| `tn_node.orphan_batches_total` | `tn_node_orphan_batches_total` | counter | `path` = `own_worker`, `worker0_fallback`, `non_validator` | close_epoch.rs:282 | one per orphaned batch by the pool it took |

## 4. Fatal or halt lines (the node stops after them)

Match on the stable phrase. "unit" = who added it; main's own are marked. Tests list the ones marked (T).

| stable phrase | full message (source text) | what stops | unit | path:line |
|---|---|---|---|---|
| `stored epoch record final_state does not match this node's closing block` (T) | `stored epoch record final_state does not match this node's closing block: this node's execution diverged from the recorded chain, stopping the node` (error; fields `epoch`, `certified`, `recorded_number`, `recorded_hash`, `local_number`, `local_hash`; counts `tn_epoch.final_state_mismatches_total`) | the node (the error is returned) | main | crates/node/src/manager/node/close_epoch.rs:1082 |
| `epoch record final_state is not the block where the epoch-closing calls ran` (T) | `epoch record final_state is not the block where the epoch-closing calls ran, stopping the node` (error line, fields in 2.3); the returned error text: `epoch {epoch}: block {n} ({hash}), the final_state of the {certified\|uncertified} epoch record ({path} path), is not the block where the epoch-closing calls ran for consensus header {n} ({hash}): {describe} - stopping the node rather than {reason} (do NOT delete chain-data: keep the datadir)` | the node; on `built`/`rederived` paths it refuses to save, vote on or publish the record | E1 | close_epoch.rs:1805 (line text :1820), Display :1851-1868 |
| `epoch record conflict halt:` (T) | `epoch record conflict halt: this node's stored record of epoch {epoch} differs from a record certified by {signers} of the {committee} members of the committee the record before it names; this node stops; do not delete its chain data before the cause is known` | the record collector ends with an error (node stops); at startup sync, startup fails; repeats on every restart | E3-FU | crates/state-sync/src/epoch.rs:262-276 |
| `own epoch record differs from a certified record in a re-certify round` | `own epoch record differs from a certified record in a re-certify round` (error, fields in 2.4) with `stop=true` | the node (`node_shutdown.notify()`), only when `epoch_record_conflict_halt` is on and `signers >= needed`; the newest and previous record stop it whatever the switch says (below) | E4-FU | crates/node/src/manager/epoch_votes.rs:974 (decision :973, notify :416) |
| `we have forked!` (T) | `Network came to consensus on epoch record {new_epoch_hash} we expected epoch record {epoch_hash}, we have forked!` | the node (`node_shutdown.notify()`), for the latest and the previous record's round | main | epoch_votes.rs:419 (message :421) |
| `leftover consensus output does not follow the last output forwarded to the engine` (T) | `leftover consensus output does not follow the last output forwarded to the engine: stopping the node before the engine executes past the gap`; returned error: `leftover consensus output gap: expected {} but received {} - stopping the node; a restart replays the missing output from the consensus DB` | the node (drain returns Err); counts `tn_node.leftover_output_gaps_total` | XF-1 | close_epoch.rs:566, :574 |
| `consensus output gap: expected` | `consensus output gap: expected {} but received {} - restarting to replay missed consensus from the DB` (error returned, no log macro) | the epoch loop errors (restart replays) | main | crates/node/src/manager/node/run_epoch.rs:846 |
| `close-time base-fee identity` | `close-time base-fee identity: canonical tip + 1 != entered-epoch blockHeight` (error line); returned error `close-time base-fee identity violated: canonical tip {} + 1 != entered-epoch {entered_epoch} blockHeight {block_height} at tip {:?} - refusing to price base fees off a non-closing block` | the close path errors | main (now counted by `tn_epoch.epoch_close_identity_check_total{result="mismatch"}`) | run_epoch.rs:1017 |
| `every later write and commit fails` | `{kind}: {cause}; every later write and commit fails` (error, target `tn_lmdb`; `kind` = `damage found` or the failure kind) | the storage environment latches; every later write and commit fails (node follows via its store-failed path) | main | crates/tn-lmdb/src/latch.rs:41 |
| `must stay below the libp2p request timeout` (startup refusal, not a log line) | `vote_timeout {:?} plus the voter's execution wait before the author lock VOTE_EXECUTION_WAIT {:?} is {:?}, which must stay below the libp2p request timeout {:?} while vote_queue_fix is on, or the transport cancels a slow vote before vote_timeout fires; lower vote_timeout below {:?} or turn vote_queue_fix off` | node refuses to start (`vote_queue_fix` on); the switch-off form is main's `vote_timeout {:?} must stay below the libp2p request timeout {:?}, ...` | PT-2C | crates/config/src/consensus.rs:553, :566 |

Not a halt on this build: the `Failed to track spawned task` error (bench 6 count line) still exists in `crates/types/src/task_manager.rs`; `tn_epoch.final_state_mismatches_total` is main's counter of the first row.

## 5. Test-hook environment variables (`crates/types/src/test_hooks.rs` at a11f14b1b)

Protection: every hook is a `pub fn` callable in all builds; with the `tn-types/test-utils` feature OFF each is a constant "off" and reads no
environment (`#[cfg(not(feature = "test-utils"))]` arms, e.g. test_hooks.rs:56, :148, :237, :284). The release image builds
`cargo build -p telcoin-network --bin telcoin-network --release --locked` (etc/Dockerfile:51, no test-utils unless `CARGO_FEATURES` adds it); the
e2e binary is built with `--features tn-storage/test-utils` (Makefile:219), which turns the hooks ON; a workspace-root build without `-p` also has them.
Each variable is read once per process (`OnceLock`); a bad value warns and leaves the hook off. No startup refusal exists.

| variable | grammar | what it does | on main? | path:line |
|---|---|---|---|---|
| `TN_TEST_EXIT_BEFORE_EPOCH_RECORD` | `<epoch>` (u64) | stop the node at the live close of that epoch after the closing block executed, before the record is written | yes | test_hooks.rs:51, :520 |
| `TN_TEST_EXIT_AFTER_EPOCH_RECORD` | `<epoch>` | stop after the record is written, before the state export / epoch tables clear | yes | :78, :524 |
| `TN_TEST_FAIL_STORE_AT_EPOCH` | `<epoch>` | fail one store of the consensus DB once that epoch's tasks run | yes | :107, :528 |
| `TN_TEST_EXECUTION_DELAY_MS` | whole milliseconds; 0/unset = off | engine sleeps this long before executing each consensus output with batches (warn `test hook: delaying the execution of every consensus output with batches`, target `engine`) | yes | :138, :156 |
| `TN_TEST_OWN_CERT_DELAY_MS` | whole milliseconds; unset/0 = hook off | hold each of this node's own certificates that long in the certifier | NO (new, HD-4a) | :226, :348 |
| `TN_TEST_OWN_CERT_DELAY_STAGE` | `before_store` \| `after_store` (unset = `after_store`) | where the hold sits (`before_store` cancels the header if a newer one arrives; `after_store` makes the certificate late) | NO | :352 |
| `TN_TEST_OWN_CERT_DELAY_EVERY` | whole number >= 1 (unset = 1) | hold only own headers whose round is a multiple of n | NO | :356 |
| `TN_TEST_WITHHOLD_EPOCH_VOTE` | `<epoch>` | keep this node's own vote for that epoch's record out of its count and off the network (with the rounds variable) | NO (new, E5a) | :267, :469 |
| `TN_TEST_WITHHOLD_EPOCH_VOTE_ROUNDS` | whole number >= 1 (read only with the epoch set; bad value = 1) | number of this node's vote rounds for that record that are withheld (original, failsafe, then re-certify picks); count restarts with the process | NO | :473 |

Not hooks of this file: `TN_SEED_SIGNATURE_FORK_EPOCH` (fork-epoch override in `tn-types` forks, main) and `TN_E2E_PARAMETERS` (e2e harness crate only, not read by the node).
**A benchmark image must have none of these set (and should be a release build without `test-utils`).**

## 6. Gone since the previous benchmark's build (bench6-contract.md names with no match under `crates/` at a11f14b1b)

Checked with `grep -rn "<name>" crates/` (underscore form and registered dotted form).
| kind | names |
|---|---|
| switches (9) | `mdbx_random_advice`, `sealed_tx_keep`, `digest_dedupe`, `recovery_threads`, `epoch_close_task_drain`, `epoch_record_state_check`, `parent_grace`, `rpc_admission_backlog_outputs`, `pipelined_persist` |
| metrics | `tn_batch_builder_sealed_txs_skipped_total`, `tn_engine_built_height`, `tn_engine_close_barrier_holds_total`, `tn_engine_commit_interval_seconds`, `tn_engine_persist_wait_seconds`, `tn_engine_unpersisted_outputs`, `tn_node_epoch_close_backlog_outputs`, `tn_node_epoch_close_detect_lag_seconds`, `tn_node_epoch_close_drain_seconds`, `tn_node_epoch_record_state_check_skipped_total`, `tn_node_epoch_record_vote_skipped_total`, `tn_node_execution_backlog_outputs`, `tn_primary_duplicate_digest_suppressed_total`, `tn_primary_late_parents_total`, `tn_primary_parent_exec_block_mismatch_total` (never built), `tn_primary_parent_grace_total`, `tn_primary_parent_grace_wait_seconds`, `tn_reth_mdbx_page_ops_total`, `tn_reth_mdbx_random_advice_bytes`, `tn_reth_mdbx_used_bytes`, `tn_reth_rpc_admission_refused_total`, `tn_reth_sealed_txs_marked`, `tn_reth_sealed_txs_cleared_executed_total`, `tn_reth_sealed_txs_cleared_repooled_total`, `tn_reth_sealed_txs_dropped_evicted_total`, `tn_reth_sealed_txs_cleared_lag_total`, `tn_reth_sealed_txs_late_marks_refused_total`, `tn_worker_duplicate_digest_suppressed_total` |
| log messages | `epoch close drained`, `stored epoch record's final state is not this node's closing block; halting`, `no executed block to compare with the stored epoch record's final state; check skipped`, `Epoch Task Manager: task tracking finished`, `mdbx random-access advice applied` / `... not applied; ...`, `batch builder started`, `kept sealed transactions in the pool`, `marking sealed transactions failed; ...`, `sealed transaction marks dropped after canonical state broadcast lag`, `sealed transaction mark sweep failed; ...`, `batch digest already reported`, `batch digest already queued`, `drained batch digest missing from the dedupe index`, `signer recovery pool failed to build - recovering on the global pool`, `parent grace armed` / `parent grace ended` / `parent grace capped at max header delay`, `pipelined persist failed - rolling back unpersisted outputs`, `pinning the output overlay failed - next output waits for the commit` |
| log fields | `grace_ms`, `waiting_for`, `still_missing`, `parent_grace_ms`, `sealed_skipped`, `keeps_sealed`, `persist_wait_ms`, `seed_ms`, `pipelined`, `detect_lag_ms`, `drain_ms`, `backlog_outputs`, the `persisted output` additions (`page_newly`, `page_cow`, `page_spill`, `page_unspill`, `page_prefault`, `page_wops`, `page_msync`, `proc_write_bytes`, `mdbx_used_bytes`, `mdbx_advised_bytes`, `mdbx_last_pgno`, `gc_entries`, `gc_large_pages`, `prefault_wchar_bytes`), and the `pool=` field of `signers recovered` (the line itself is main's) |
| label values | `tn_primary_late_parents_total{origin}`, `tn_primary_parent_grace_total{outcome}`, `tn_node_epoch_record_vote_skipped_total{reason}` (all with their metrics) |

Still present from bench 6 (so not stale): `tn_primary_epoch_entry_rounds_behind`, the sub-ms histograms (section 3.1), the `prelock_wait` stage and `superseded` outcome, `oldest_requeue_wait_ms`, the first-receipt `tn_primary_digest_wait_seconds`, switches `quorum_exec_block`, `quorum_exec_block_starved_rounds`, `vote_queue_fix`.
Not re-checked in this file (outside the diff of this stack): the `sender` field on `skipping invalid transaction` and the generator/harness names of bench6-contract.md.

## 7. Disagreements (unit notes vs code at a11f14b1b; the code wins)

| # | unit note says | code says | where |
|---|---|---|---|
| 1 | E3 note: the halt message says "forked" (brief); PT-3b e2e constant `CONFLICT_HALT_LOG` = `this node's epoch record differs from a certified record of the network: this node has forked and stops; do not delete its chain data before the cause is known` (`FATAL_LOGS` member) | the halt line is `epoch record conflict halt: this node's stored record of epoch {epoch} differs from a record certified by {signers} of the {committee} members of the committee the record before it names; this node stops; do not delete its chain data before the cause is known` (E3-FU item 2 changed it); no text of the e2e constant is in the code, so a harness or test matching the old constant never sees the halt | crates/e2e-tests/tests/it/exec_block.rs:89-91, :102; crates/state-sync/src/epoch.rs:262-276 |
| 2 | PT-3a/E-era doc of `quorum_exec_block_starved_rounds`: "applies the rule only for `K` rounds after ... cancelled" (PT-3c flagged it, replacement text left to the orchestrator) | the window counts HEADERS BUILT, not rounds (a round jump does not spend it) | crates/config/src/node.rs:347 vs crates/consensus/primary/src/proposer.rs `ExecBlockPolicy` doc (~:2068-2075) |
| 3 | XF-1b note: fields `digest=%consensus_header_hash` | `digest = ?output.consensus_header_hash()` (Debug, not Display) on both `skipping already-forwarded consensus output` lines | close_epoch.rs:554; run_epoch.rs:834 |
| 4 | E4 note: re-certify rounds never write `tn_node.epoch_record_signers` | E4-FU V10: rounds of the latest and the previous record write it, rounds of older records do not; label `round` on missing signers | crates/config/src/node.rs:365-368; epoch_votes.rs:512, :1283 |
| 5 | bench6-contract.md: `node switches` lists 12 switches and the bench-6 line; stored-record halt text `stored epoch record's final state is not this node's closing block; halting` | 7 switches; main's `stored epoch record final_state does not match this node's closing block: ...` | section 1; close_epoch.rs:1082 |
| 6 | HD-1 api: `HD-1 sets own_parent ... and leaves the counts 0` | final code fills `held`, `held_lanes`, `blockers` from the plan (HD-2b); with the switch off they are 0 and `own_parent` is still computed | proposer.rs:525, `drain_held` ~:1285 |
| 7 | pt0-api.md: gauge written `tn_node_switch{name}` | consistent with code, but the registered name has no dot (`tn_node_switch`), unlike the other `tn_node.*` series | crates/node/src/metrics.rs:13 |
