# Draft PR (telcoin-network) — topic `land-path-obs` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Opened as #1819 (2026-11-10): head `feat/land-path-obs` → base `staging/benchmark-obs-2026-11` (PR 8 of 10, stacked). Final body: tasks/pr-bodies/bench5-07-land-path-obs.md.

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/land-path-obs origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: land-path-obs$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): dac760298 d660e8e7f 0bd522ca7 cafca0d95
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: tasks/bench5-land-time-baseline.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/land-path-obs --title "<title>" --body-file <this file's body>

## Title
feat: time-to-land stage instrumentation (batch, worker, proposer, commit path, fetch and pack persist)

## Body (per-commit summary)
- dac760298 `feat(batch-builder): record build reason, pool age and wake source per sealed batch`
  Bench 4 could not split stage S1 (pool wait) of time to land: the builder exported only its seal duration, and
    the I-3 baseline found that under load S1 is 1-5 s of nonce-gap parking in reth's queued sub-pool (240-3,365
    txs per node on average), not the 125 ms mean tick wait. Every sealed batch now logs one `batch built` line
    (target consensus::metrics) with its digest, size, gas, why selection stopped (drained, gas_full, bytes_full),
    the median and oldest pool age of its transactions, the build time, the pending and queued pool sizes before
    the build and what woke the loop (tick, canonical, ack); metrics tn_batch_builder.pool_age_seconds (oldest age
    per batch) and builds_total{worker,reason}. Batch contents and seal are unchanged.
- d660e8e7f `feat(worker): stamp digest, quorum and report timing on the seal lines`
  The bench-4 land-time join could not follow a batch from the builder to its header: `batch sealed` carried no
    digest, and quorum and report timing (stages S2 and S3) existed only as the fleet-wide quorum_wait_seconds
    histogram (0.14-0.29 s per node under load). `batch sealed` now appends `digest` and `quorum_ms` (from handing
    the batch to the quorum waiter until its result); a new consensus::metrics line `batch reported digest=
    report_ms= report_us=` follows a successful report. tn_worker.batch_report_seconds times every report and, as
    the in-process report is normally sub-millisecond, takes the sub-ms bucket layout. Existing texts and fields
    are unchanged.
- 0bd522ca7 `feat(executor,state-sync,storage): time batch fetch and pack persist per output`
  Bench 4's time-to-land breakdown (r20261105-0803) had no figure for two subscriber stages every output waits on:
    the batch fetch and the consensus pack persist before it is published and forwarded. Bench 5's 600 x 4 arm
    asks whether throughput holds with smaller outputs, where that persist is a fixed cost per output. `consensus
    output ready` gains fetch_ms (end of the execution wait to the assembled output) and leader_epoch; a new
    `output saved` line carries the pack's and the slot files' persist times, and
    tn_executor.consensus_pack_persist_seconds records the pack's. save_consensus returns both times from the
    chain's timed persist, now public. What is saved, when and in what order is unchanged.
- cafca0d95 `feat(primary): proposer digest wait, header reason and commit-path timestamps`
  Bench 4's time-to-land baseline (r20261105-0803) could not join a batch to its header or date a commit apart
    from the execution wait: `header proposed` named no digests, the commit lines carried no creation times, and
    own headers that lost their votes logged at debug only. Idle, the stages these lines bound (digest wait, own
    certificate to the committing leader, leader to commit) are 1.11 s of the 1.88 s floor. The proposer now
    stamps each digest's arrival and reports per header the condition branch that fired, the digests, the oldest
    digest's wait and the queue depth (`digest_wait_seconds`; `headers_proposed_total` gains a `reason` label on
    every series), and logs `digests resent` on a re-queue. The certifier logs `header uncertified` when a newer
    header cancels the votes or no certificate forms; `certificate committed` and `subdag committed` gain creation
    and commit timestamps; `subdag sequenced` marks the hand-off to the subscriber after the run-ahead gate. Log
    and metric fields only: what is proposed, certified, committed and sequenced is unchanged.

## Why (measured motivation)
See the issue text tasks/bench5-land-time-baseline.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- The join works end to end: `benchmark/tools/stage-latency.py` reproduces every block's stage chain S0-S13 from these lines; Σ stages − seen ≤ 250 ms on 100 % of light-load blocks and 97-99 % under load (A6/stages.md).
- Measured floor (8-16 senders): time to land (leader header created) 0.65 s, to commit 1.25 s, to seen 1.50 s — against a predicted 1.2 / 2.2 s. At light load the leader-created → commit stage (611 ms) is 40 % of seen and consensus (S2-S6b) 82 %.
- At saturation the engine queue is 9.6 of 14.9 s seen; one output costs 1,658 ms = execute 479 + persist 1,167 (MDBX commit 1,035). Persist is off the visibility path (blocks are on RPC once executed).
- Little's law holds (ratio 0.97-1.04): 600 × 4 → 4,006 tx/s at mean seen 4.59 s; 600 × 16 → 3,481 tx/s at 23.69 s.
- The ranked levers from these numbers are in A6/levers.md (node-side in-flight bound, pipelined persist, far-validator certificate inclusion, the F3-6 fix, #532).

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
