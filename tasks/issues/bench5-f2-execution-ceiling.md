# Engine execution caps chain throughput at about 215 µs per transaction

## Problem

On an 11-node benchmark network under sustained load the engine is the throughput limit. It is busy about 98 % of
wall time on every node, its queue sits at `MAX_QUEUED_OUTPUTS = 8`, and it costs about 215 µs per transaction, which
caps the chain near 4.6 k tx/s. Execution is 75 % of each output's task time and the durable persist 24 %. Every landed
transaction also waits 7-9 s in the engine queue before its own output runs, so the same ceiling sets most of the
end-to-end latency.

Part of the execution time is not execution. With the engine target at debug, the executing thread formats a Debug
dump of every `ConsensusOutput` (raw transaction bytes included) and of every `ExecutedBlock`, plus two or three lines
per transaction. Those lines wrote 1.16 GB per minute per validator under load. How much of the 165 µs/tx execute
time they cost has not been measured, because the engine reports one `execute_ms` number per output.

## Evidence

Run r20261105-0803, build 496ebefb5 (main plus observability commits), load window 09:11:59-09:33:50 UTC, v01 unless
noted. The other healthy validators agree within a few per cent.

- Saturation: `rate(tn_engine_busy_milliseconds_total)` 976-988 ms/s in every 5-minute bucket of load on all 11 nodes
  (891 during warm-up); `tn_engine_queued_outputs` at 8; `output execution task finished queue_wait_ms` 7.3 s p50,
  11.1 s p95.
- Split per non-empty output (627 outputs): task 1.79 s p50 (mean 2.08 s); `execute_ms` 1.29 s p50 (75 %),
  `persist_ms` 0.49 s p50 / 0.86 s p95 (24 %), `announce_ms` 11 ms.
- Inside the persist (`persisted output`): commit 70 % (357 ms p50), `save_blocks` 30 % (126 ms). The MDBX commit is
  almost all fsync: `reth_database_transaction_commit_sync_duration_seconds` p50 0.33-0.38 s against a write p50 at
  the 2.5 ms bucket floor.
- Flat per transaction, by 5-minute bucket: task 185 µs/tx at 09:10, 231 at 09:15, 212 at 09:45; execute 138 to
  166 µs/tx, flat from 09:15; persist 46, 64, 45 µs/tx. Outputs grew from 8.1 k to 12.5 k transactions as rounds slowed
  (0.61 to 0.33 outputs/s), so each output carried proportionally more work.
- Log volume, v01:09:30 (a loaded minute): 1,163 MB/min written, 1,160 MB of it `target=engine` (about 10,000
  lines/s). In a 10-second sample (v01:09:30:00-09:30:10, 198 MB): `block executed` 57 % (158 lines, about 716 kB
  each), `executing output` 19 % (2 lines, about 18.7 MB each), `governance collects` 11.5 % and `allocating
  basefees` 11 % (48,806 lines each, about 4,900/s, the transaction rate), `usage within acceptable range` 1 %
  (first seen v01:10:15:01.220Z with `gas_limit=250000`). The unit log reached 49 GB per validator in two hours.
- The same sample gives the block shape: about 309 transactions per block and about 40 blocks per 12.5 k-transaction
  output.

## Mechanism

Line numbers are at 4bf4604d2 unless marked "obs" (the observability commits that add the timing lines).

One output executes at a time. `ExecutorEngine::run` stops polling the consensus stream once
`self.queued.len() < MAX_QUEUED_OUTPUTS` fails (`crates/engine/src/lib.rs:271`, constant at `:52`) and spawns one
blocking task per output (`:159`). Behind it, the epoch manager's `to_engine` channel holds up to 64 more outputs
(`crates/node/src/manager/node.rs:77-85`, created at `:873`, sent at `run_epoch.rs:694`). The queue-wait stamp starts
at the engine's `push_back` (`lib.rs:275`), so time spent in that channel is not measured anywhere.

Inside the task, `execute_consensus_output` (`crates/engine/src/payload_builder.rs:25`) does, on the one thread:

1. `debug!(target: "engine", ?output, "executing output")` at `:62`: the derived Debug of the whole output, including
   every certificate header and every batch's `transactions: Vec<Vec<u8>>` printed as decimal byte lists.
2. For each batch, `execute_payload` (`:329`) calls `RethEnv::build_block_from_batch_payload`
   (`crates/tn-reth/src/env/execution.rs:134`), then logs `?next_canonical_block` at `:340` (the whole
   `ExecutedBlock`: transactions, bundle state, receipts, sorted trie deltas).
3. Inside `build_block_from_batch_payload`:
   - `?parent_header` at `:141`, once per block.
   - A fresh `CachedReads::default()` per block at `:145`. Every block re-reads, through reth's
     `MemoryOverlayStateProvider`, the accounts and slots that earlier blocks of the same output already read. Each
     miss scans every unpersisted block of the output before reaching MDBX (reth `chain-state/src/memory_overlay.rs`
     `basic_account` and `storage`), and an output has about 40 blocks.
   - Signer recovery for the batch on the global rayon pool at `:181` (unrecoverable transactions dropped with an
     `error!` that prints the raw bytes, `:185-190`). The executing thread waits for it.
   - The sequential transaction loop at `:210-229`, with a `recovered.clone()` per transaction at `:212`. The EVM
     handler logs two debug lines per transaction (`crates/tn-reth/src/evm/handler.rs:132` `governance collects`,
     `:181` `allocating basefees`) and a third for transactions with a gas limit above 210,000
     (`crates/tn-reth/src/evm/utils.rs:68`). Every one of these lines also carries the fields of the
     `execute-consensus` span (`payload_builder.rs:52`).
   - `builder.finish(&root_provider)` at `:234-239`: the epoch-close system calls on a closing block, the bundle
     merge, `hashed_post_state`, the single-threaded layered state root (`OverlayRootStateProvider`,
     `env/output_overlay.rs:225-231`) and block assembly.
4. One persist for the whole output, `persist_executed_output` (`execution.rs:316`): `save_blocks(Full)` (`:331`)
   and one `provider_rw.commit()` (`:344`), which finalizes and syncs the static files and then commits MDBX with an
   fsync. Then the announce (`payload_builder.rs:312`) and `finalize_block` (`:318`).

The node's stdout log layer formats and writes each line synchronously on the calling thread (reth-tracing's stdout
layer uses the default `std::io::stdout` writer). When the file layer is enabled with the same filter, as the
benchmark did, each dump is formatted a second time before the non-blocking file writer takes it.

## Proposal

None of the changes below alters a block. Transaction order, block contents, state roots, receipts, gas, timestamps
and the consensus pack stay byte-identical; the tests in the next section compare them.

1. Demote the dumps (`log-dumps`). `payload_builder.rs:62` becomes `trace!(target: "engine::dump", ?output)` plus a
   debug line with `consensus_number`, `batches` and `txs`; `:340` becomes a trace under `engine::dump` (the info line
   after it keeps hash and number); `handler.rs:132`, `:181` and `utils.rs:68` become `trace!(target: "engine::evm")`;
   `execution.rs:141` (`?parent_header`) and `lib.rs:289` (`?res`) become trace. An `engine=debug` filter
   prefix-matches the new targets but not at trace, so the three timing lines (`output execution task finished`,
   `output executed`, `persisted output`) stay visible and the dumps go away. Consensus-neutral: logging only.
2. Split `execute_ms` (`exec-split`). Lap the block build into `recover`, `evm` (builder setup, pre-execution system
   calls and the transaction loop), `root` and `finish`, sum them per output, and add `txs recover_ms evm_ms root_ms
   finish_ms other_ms max_block_root_ms max_block_evm_ms` to `output executed`, with histograms
   `tn_engine_{recover,evm,root,finish}_seconds`. `root` must be timed inside
   `OverlayRootStateProvider::state_root_with_updates`, because `builder.finish` also runs the closing system calls,
   the bundle merge, `hashed_post_state` and block assembly; `finish` is the rest of `builder.finish` plus the bundle
   take, the delta sorts and the overlay extend. `other_ms` (execute minus the laps) is where the dumps lived. The
   current signature stays as a wrapper so its 21 test call sites do not change. The per-transaction clone goes:
   `let tx_hash = *recovered.tx_hash()` before `builder.execute_transaction(recovered)`. reth implements `ExecutorTx`
   for `Recovered<T>` by value, and typed transactions cache their hash at decode, so the hash read is free and the hash
   is not an execution input.
3. Time the subscriber-to-engine hop (`exec-split`). Stamp the output with an `Instant` in `process_output` immediately
   before `to_engine.send(..).await` and record `tn_engine_forward_wait_seconds` at the engine's `push_back`;
   export `tn_engine_channel_depth` from `Receiver::len` (tokio 1.53, reached through `ReceiverStream`'s
   `AsRef<Receiver<T>>`); add `forward_wait_ms` to `output execution task finished`. A transient, non-serialized
   field on `ConsensusOutput` (like `close_epoch`) carries the stamp without changing the channel type. A tuple would
   change eleven production signatures (seven on the sending side, four in the engine) and 22 engine test
   constructions. Consensus-neutral: the field is
   never serialized or hashed.
4. Recover signers when an output is queued (`signer-reuse`). On `push_back`, spawn a blocking job that recovers every
   batch of the output with the same function, the same order and the same drop rule as `execution.rs:181`, returning
   one `Vec<Recovered<TransactionSigned>>` per batch in `flatten_batches()` order. The execution task
   `blocking_recv()`s the result (safe on a `spawn_blocking` thread; the announce already calls `blocking_send` there)
   and builds through a `build_block_from_recovered_payload` entry point. If the job panicked, the task recovers the
   same bytes inline instead of failing. `recover_ms` becomes `recover_wait_ms`. Memory: decoded transactions are
   about 0.4-0.6 kB each, so at most `MAX_QUEUED_OUTPUTS + 1` outputs of about 5-7.5 MB each at bench-4 sizes.
   Reusing the batch validator's recovery is not proposed: it discards the signer (`txn_pool.rs:1157-1161`) and never
   sees the node's own batches, restart replay or synced outputs. Consensus-neutral: the same recovery of the same
   bytes, so the same transactions are dropped and the rest execute in the same order.
5. Keep one read cache across the blocks of an output (`cached-reads`). Pass one `CachedReads` through the output
   beside the trie overlay, re-wrapped over each block's own parent-state provider (so cache misses read the right
   parent state). After each successful block, apply that block's bundle to the cache: an account whose status
   `was_destroyed()` or whose `info` is `None` is removed; any other changed account gets its new `info` with the code
   stripped (`without_code()`, which is what the state provider returns) and its changed slots set to their
   `present_value`; untouched entries stay. The invariant is that every cache entry equals the parent state of the next
   block, which makes a hit indistinguishable from a provider read. Sharing one revm `State` across blocks is
   rejected: `DestroyedChanged` is sticky in revm, and reth marks a destroyed-status account's storage as wiped in
   `hashed_post_state`. With a CREATE2 factory, block 1 creates contract A and self-destructs it in the same
   transaction, block 2 recreates A and writes slot 1, block 3 writes slot 2. Under a shared `State`, block 3 still
   reports A as `DestroyedChanged`, its hashed storage is wiped, and the root drops slot 1. With the per-block cache
   update, A is removed after block 1 and every later read matches a fresh build.

Not in this change, and what each would need:

- Pipelined persist (commit output N while N+1 executes; the fsync is about 0.35 s of every 1.8-2.7 s output). The
  overlay assumes the database tip is its anchor for the whole output (`output_overlay.rs:53-56`, `:152-156`) and
  opens a fresh read-only transaction per root (`:229`). With N's commit in flight, N+1's root can see either side of
  it, so the overlay has to carry N's deltas and pick its anchor from the snapshot's `best_block_number()`.
  `finalize_block` must not prune N's blocks from memory before N commits. A failed persist of N after N+1 executed
  must roll back both and halt. It also needs a crash test between execute and commit.
- A parallel state root, if `root_ms / txs` from item 2 is large. reth's parallel root opens one read-only
  transaction per worker; each needs the same anchor and the output overlay layered under it.
- `--db.sync-mode safe-no-sync`. The flag already reaches MDBX (`tn-reth/src/cli.rs:95-97` flattens reth's
  `DatabaseArgs`; `env/mod.rs:293` passes it to `init_db`) and removes only the MDBX fsync; static files still sync in
  `commit`. A process crash is safe. An OS crash or VM reset can roll MDBX back many outputs. `check_consistency`
  (`env/mod.rs:438`) then has to prune static files by more than one block, which is untested, and
  `replay_missed_consensus` refuses to start if the lost range crosses an epoch boundary
  (`node/src/manager/node/start_epoch.rs:135-145`). It should stay an opt-in benchmark arm until both paths have tests.

## Test plan

- Item 1: none beyond fmt and clippy. It changes log levels only.
- Item 2: extend `test_metrics_register_and_update` (`crates/engine/src/metrics.rs`) with the four histograms; unit
  test `OutputTimings::add` (sums, per-block maxima); a tn-reth test that a block with state changes reports a non-zero
  `root` lap and that the laps never exceed the total.
- Item 3: adapt `test_queued_outputs_bounded_with_backpressure` (`crates/engine/tests/it/main.rs:246`) to assert
  `tn_engine_channel_depth` while the channel is full; a test that a stamped output records one forward-wait sample and
  an unstamped one records none.
- Item 4: point `crates/tn-reth/tests/it/recover_drop_props.rs` at the recovery function (undecodable-only batch gives
  an empty block; mixed batch keeps the valid transaction). Add an engine differential test: the same multi-batch
  output built from bytes and from pre-recovered transactions gives the same block hashes, state roots, receipts roots
  and gas. Add a duplicate-transaction test across two batches and a test that a failed recovery job falls back to
  inline recovery.
- Item 5: a unit test of the cache update on a synthetic `BundleState` covering `Destroyed`, `DestroyedChanged`,
  `info: None`, a changed contract (code stripped) and an untouched entry. A differential integration test in
  `crates/tn-reth/tests/it/` that builds the same unpersisted 3-4 block output twice, once with a fresh cache per
  block and once with the shared cache (the pattern of `trie_overlay.rs`
  `test_unpersisted_chain_roots_match_memory_overlay_oracle`), including the CREATE2 self-destruct and recreate
  sequence above, an EIP-161 touched-empty account and a sender repeated across blocks. It asserts equal block hashes,
  state roots and bundles (bundle equality ignores `AccountInfo.code`, so assert the stripped cache contents
  separately). Finish with a proptest of random transfers over `PipelineTestEnv`.

## What the next benchmark run reads

- `output executed`: `recover_wait_ms` (expected near 0 under load), `evm_ms`, `root_ms`, `finish_ms`, `other_ms` per
  transaction and per 5-minute bucket, against bench 4's execute 138-166 µs/tx. `root_ms / txs` decides whether a
  parallel state root is the next execution item.
- Task µs/tx and `rate(tn_engine_busy_milliseconds_total)`: lower per-transaction cost at the same busy fraction means
  more chain throughput.
- `output execution task finished forward_wait_ms` and `tn_engine_channel_depth`: the backlog upstream of the engine
  queue, which bench 4 could not see.
- The unit log rate under load: bench 4 wrote 1,163 MB/min on v01; after item 1 it should be a few MB/min.
- The persist split from reth's own series (`reth_storage_providers_database_save_blocks_*`, including
  `save_blocks_commit_mdbx` and `save_blocks_commit_sf`) next to `persisted output` `commit_ms`, which sizes the
  pipelined-persist and sync-mode work.

Items 1, 4 and 5 ship in one build, so the drop in execute µs/tx against bench 4 cannot be split between them from
the run alone. A Criterion benchmark of the execute path on a 12 k-transaction output, once with a debug subscriber and
once without, attributes the logging share offline.
