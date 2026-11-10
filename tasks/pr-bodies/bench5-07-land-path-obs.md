## Summary

Adds the log lines and metrics that time a transaction's path to landing stage by stage: the batch builder's build
reason, pool age and wake source; digest, quorum and report timing on the worker's seal lines; batch fetch and pack
persist per output; and the proposer's digest wait, header reason and commit-path timestamps. Log and metric fields only:
what is built, sealed, proposed, certified, committed and saved is unchanged.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

Bench 4 (r20261105-0803) produced a time-to-land baseline that splits a transaction's path into stages S0-S13, but
several stages had no measurement or could not be joined to the next one:

- S1, the pool wait: the builder exported only its seal duration. The baseline found that under load S1 is 1-5 s of
  nonce-gap parking in reth's queued sub-pool (240-3,365 transactions per node on average), not the 125-ms mean tick
  wait.
- S2 and S3, quorum and report: `batch sealed` carried no digest, so a batch could not be followed from the builder to
  its header, and quorum and report timing existed only as the fleet-wide `quorum_wait_seconds` histogram (0.14-0.29 s
  per node under load).
- The subscriber's batch fetch and consensus pack persist, which every output waits on before it is published and
  forwarded, had no figure. Bench 5's 600 × 4 arm asks whether throughput holds with smaller outputs, where that persist
  is a fixed cost per output.
- `header proposed` named no digests, the commit lines carried no creation times, and own headers that lost their votes
  were logged at debug only. A batch could not be joined to its header, and a commit could not be dated apart from the
  execution wait. Idle, the stages these lines bound (digest wait, own certificate to the committing leader, leader to
  commit) are 1.11 s of the 1.88-s floor.

## Fix

- {{SHA:dac760298}} `feat(batch-builder): record build reason, pool age and wake source per sealed batch`: every sealed
  batch logs one `batch built` line (target `consensus::metrics`) with its digest, size, gas, why selection stopped
  (`drained`, `gas_full`, `bytes_full`), the median and oldest pool age of its transactions, the build time, the pending
  and queued pool sizes before the build and what woke the loop (`tick`, `canonical`, `ack`). Metrics:
  `tn_batch_builder.pool_age_seconds` (oldest age per batch) and `builds_total{worker,reason}`. Batch contents and seal
  are unchanged.
- {{SHA:d660e8e7f}} `feat(worker): stamp digest, quorum and report timing on the seal lines`: `batch sealed` appends
  `digest` and `quorum_ms` (from handing the batch to the quorum waiter until its result), and a new `consensus::metrics`
  line `batch reported digest= report_ms= report_us=` follows a successful report. `tn_worker.batch_report_seconds` times
  every report and, since the in-process report is normally sub-millisecond, uses the sub-ms bucket layout. Existing
  texts and fields are unchanged.
- {{SHA:0bd522ca7}} `feat(executor,state-sync,storage): time batch fetch and pack persist per output`: `consensus output
  ready` gains `fetch_ms` (end of the execution wait to the assembled output) and `leader_epoch`; a new `output saved`
  line carries the pack's and the slot files' persist times, and `tn_executor.consensus_pack_persist_seconds` records the
  pack's. `save_consensus` returns both times from the chain's timed persist, now public. What is saved, when and in what
  order is unchanged.
- {{SHA:cafca0d95}} `feat(primary): proposer digest wait, header reason and commit-path timestamps`: the proposer stamps
  each digest's arrival and reports per header the condition branch that fired, the digests, the oldest digest's wait and
  the queue depth (`digest_wait_seconds`; `headers_proposed_total` gains a `reason` label on every series), and logs
  `digests resent` on a re-queue. The certifier logs `header uncertified` when a newer header cancels the votes or no
  certificate forms; `certificate committed` and `subdag committed` gain creation and commit timestamps; and `subdag
  sequenced` marks the hand-off to the subscriber after the run-ahead gate.

## Testing

{{TESTING:07}}

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- The join works end to end: the bench's stage-latency script reproduces every block's stage chain S0-S13 from these
  lines, with Σ stages − seen ≤ 250 ms on 100 % of light-load blocks and 97-99 % under load.
- Measured floor at 8-16 senders: time to land (leader header created) 0.65 s, to commit 1.25 s, to seen 1.50 s, against
  a predicted 1.2 / 2.2 s. At light load the leader-created → commit stage (611 ms) is 40 % of seen, and consensus
  (S2-S6b) is 82 %.
- At saturation the engine queue is 9.6 of 14.9 s seen. One output costs 1,658 ms = execute 479 + persist 1,167 (MDBX
  commit 1,035). Persist is off the visibility path: blocks are on RPC once executed.
- Little's law holds (ratio 0.97-1.04): 600 × 4 gives 4,006 tx/s at a mean seen of 4.59 s; 600 × 16 gives 3,481 tx/s at
  23.69 s.
- The bench-5 report ranks the levers these numbers point to (finding 5): a node-side in-flight bound, pipelined
  persist, far-validator certificate inclusion, the F3-6 fix and #532. The far-validator analysis
  ({{ISSUE:far-validator-certificate-inclusion}}) reads its drift and orphan figures from these lines among others
  (`header proposed`, `digests resent`, `certificate committed`).

Refs {{ISSUE:far-validator-certificate-inclusion}}
