# Draft PR (telcoin-network) — topic `exec-split` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/exec-split origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: exec-split$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 3dc26fa59 fac145464 decc4cbc4
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: tasks/issues/bench5-f2-execution-ceiling.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/exec-split --title "<title>" --body-file <this file's body>

## Title
feat(engine): split execute time per output, time the subscriber-to-engine hop, name the consensus ids on executed blocks

## Body (per-commit summary)
- 3dc26fa59 `feat(engine): split execute_ms into recover/evm/root/finish per output`
  Bench 4 executed at 215 us/tx, 165 us/tx of it in execute_ms: too coarse to say whether bench 6 should
    parallelise the state root. build_block_from_batch_payload_timed returns the laps (the old call wraps it) and
    times the root inside the overlay root provider, as reth runs it in finish. `output executed` appends txs, the
    laps, other_ms and the slowest block's root and evm laps; tn_engine_{recover,evm,root,finish}_seconds are the
    only execute-only series (execution_duration times the whole task); tn_engine_executed_transactions_total
    gives a per-tx rate. A test shows the wrapper transparent and the build deterministic; parity with the old
    loop rests on passing the same Recovered<T> by value (no clone) and on the reth-oracle root test, via the
    timed root provider.
- fac145464 `feat(engine): time the subscriber-to-engine hop and export channel depth`
  Bench 4's queue_wait saw only the engine's own 8-slot queue; the 64-slot to_engine channel in front of it, where
    outputs back up once execution falls behind, had no measurement. ConsensusOutput gains a transient
    forwarded_at stamp (like close_epoch: never serialized, hashed or executed), set in process_output just before
    the one send to the engine. The engine records tn_engine_forward_wait_seconds when it takes an output off the
    channel, appends forward_wait_ms to `output execution task finished`, and samples the depth left behind into
    tn_engine_channel_depth on every arrival and completion. A field instead of an (Instant, ConsensusOutput)
    tuple leaves the 11 forwarding signatures and 22 test call sites untouched.
- decc4cbc4 `feat(engine): queued line and consensus ids on executed blocks`
  The bench-5 land-path breakdown joins its stages on the consensus number and the batch digest, but the engine's
    side of that join was incomplete: an output reaching the engine queue was not logged, and `next block
    executed` named only the block hash and number while its enclosing span carried consensus_number; the explicit
    field is what the offline join parses. The engine now logs `output queued` at debug with the consensus number
    and the queue depth after the push, and `next block executed` appends consensus_number, batch_index and
    batch_digest, so the queue and execute stages of every block join back to their output and batch. One line per
    output or block, never per tx; an engine test captures the lines and pins the field order of the engine's
    timing lines too.

## Why (measured motivation)
See the issue text tasks/issues/bench5-f2-execution-ceiling.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- The split is the F2 measurement: at saturation execute = 87.4 µs/tx = recover_wait 0.0 + evm 26.5 + root 49.2 + finish 11.4 + other 0.2; persist = 199.2 = save_blocks 21.1 + commit 178.0 (median of ten validators, A4n/f2.json). 1 / (87.4 + 199.2) µs = 3,465 tx/s, within 0.5 % of the measured 3,449 tx/s.
- `root_ms` is 56 % of execute: the parallel state root is the next execute item (worth ≤ 49 µs/tx).
- `forward_wait_ms` + `tn_engine_channel_depth` showed the suspected 64-slot backlog does not exist: channel depth ≤ 2, consensus commits at the execution rate (0.573 vs 0.559 outputs/s); the queue (cap 8) sits at its cap only on the three slowest executors.
- The same lines exposed the run's main surprise: the MDBX commit is 1.03-1.06 s per output on every node (bench 4: 0.30-0.34 s) with identical logical writes — see tasks/issues/bench5-persist-fsync-amplification.md.

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
