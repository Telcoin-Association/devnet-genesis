## Summary

Adds the log lines and metrics that the bench-4 and bench-5 analyses were built on: the voter's vote path by stage,
proposer vote round trips, engine execute, persist and commit timings, node mode transitions with reasons, the scheduled
leader of every round, batch-serve denials and epoch-record signers. Observability only: no behaviour change and no new
dependencies.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. This is the first PR, based directly on the staging branch at c65abdf79, so the Files tab shows only its own commits; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/c65abdf79...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

Bench 4 (r20261105-0803) asked eight questions of a loaded ten-validator network: where a voter waits (Q1), what the
proposer side adds (Q2), how leader rounds are shared (Q3), whether execution or persist bounds throughput (Q4), why a
promoted validator falls back (Q5), whether batch serving starves (Q6), how epoch records reach quorum (Q7) and whether
V1Lazy (#1783) gives one round trip per vote (Q8). Main's logs and metrics could answer none of them.

Two failures were already happening on origin/main and could not be seen: the commit-lag demotion
({{ISSUE:f1-commit-lag-demotion}}) and the promotion loop ({{ISSUE:f3-rejoin-loop}}). `we are behind, go to catchup
mode!` and `failed to reach quorum on epoch close` predate these commits, but without the fields that now name the cause.

## Fix

One bullet per commit. The bench-4 build carried the same commits under the shas in parentheses; the evidence below cites
those.

- {{SHA:77539d77d}} `feat(network): label outbound request durations by service class and log request resolution`
  (bench 4: 94b0d8cd9): `tn_network_outbound_request_duration_seconds{outcome,class}` and `network::reqres` debug lines
  (`inbound request`, `response sent`, `response received`, `outbound request failed`) with peer, request_id, class and ms.
- {{SHA:e938be258}} `feat(primary): time the voter's vote path by stage and count vote outcomes` (bench 4: 7a9ac247e): the
  voter's vote path stamped by stage (lock, validate, exec_wait, parents, lead_sleep, sync_batches, vote_store, persist),
  giving one `vote path timing` line per request, `tn_primary_vote_stage_seconds{stage}`, vote outcome counters,
  `vote timeout fired` with the stage in progress, an explicit `vote refused: header too new` and header batch sync lines.
- {{SHA:49643180d}} `feat(primary): stamp proposer vote round trips, persist barrier and proposal lock` (bench 4:
  8663c297b): the proposer side. Per-peer vote round trips on every response (round, attempt, elapsed_ms), `vote requests
  issued` (header_age_ms, peers), `proposal lock acquired` (lock_wait_ms) and `header stored and sent`
  (read/write/persist/send ms).
- {{SHA:4ab917aae}} `feat(engine): split execute, persist and commit timings and count engine busy time` (bench 4:
  b539caf1c): queue wait, busy milliseconds and persist duration on `EngineMetrics`; `output executed`
  (execute/persist/announce ms) and `persisted output` (open/save_blocks/markers/commit ms, accounts, storage slots) with
  `tn_reth_persist_*` series.
- {{SHA:180a2d8c1}} `feat(subscriber): log rejoin blockers and count node mode transitions with reasons` (bench 4:
  d66ce4892): `tn_node_mode_transitions_total{to,reason}` at every demotion and promotion site, a `RejoinBlocker`
  classification with throttled `rejoin not ready` lines and `tn_executor_rejoin_blocked_total{reason}`, round fields on
  the behind-consensus, rejoin and reproposing lines, and a `dag restored` span.
- {{SHA:c6e8df6dd}} `feat(primary): log the scheduled leader of every round and count leader outcomes` (bench 4:
  7725b8543): `scheduled leader` per decided leader round (swapped, found), `tn_primary_leader_rounds_total`,
  `tn_primary_leader_commits_total{leader}`, the leader named on `subdag committed`, and `leader_with_swap` primitives.
- {{SHA:2d47fe191}} `feat(worker): count batch-serve denials and denied batch requests` (bench 4: 8a92c088d):
  `tn_worker_sync_serves_denied_total{worker,tier}`, `tn_worker_batch_requests_{denied,failed}_total{worker,peer}` and
  elapsed_ms on the pool-full denial line.
- {{SHA:f7936def8}} `feat(epoch-manager): log missing epoch record signers and signer counts` (bench 4: 1374afa17):
  `epoch record quorum` with signers, committee, timeouts and `missing=[ids]`, `tn_node_epoch_record_signers` and
  `tn_node_epoch_record_missing_signers_total{signer}`.
- {{SHA:3a721a1b6}} `fix(observability): sub-millisecond stage buckets, quieter batch-sync lines and review follow-ups`
  (bench 4: 496ebefb5): a sub-ms bucket layout for the vote-stage and queue-wait histograms (Full matchers), batch-sync
  abandon lines at debug, and review follow-ups (watch borrow, lock-held increments, variant-order asserts).

## Testing

{{TESTING:00}}

On the bench branch the nine commits passed the libp2p and primary suites (916 tests), the three #1783 tests, fmt and
clippy.

## Evidence (bench 5, run r20261107-1504)

The same nine commits, on top of origin/main 4bf4604d2, carried the bench-5 fix build, and the lines were again the
evidence. Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- `vote path timing … outcome=behind exec_wait_ms=1001` on seven voters at once is how the F3-6 regression was found: the
  three fastest executors' headers were refused by every slower voter and certified 0.2 / 0.0 / 16.3 % of the time under
  load ({{ISSUE:execution-behind-vote-starvation}}). The per-node refusal counts matched the counters within 1.5 %.
- `vote refused: header too new` fell from 100,852 lines (bench 4) to 12: the TooNew storm was a symptom of the
  commit-lag demotion.
- `header uncertified round= epoch= reason=` and `digests resent … cause=canceled` sized the cert-requeue change (2,811 of
  2,813 cancelled headers' digests landed in the next header, 113-118 ms later) and showed it cannot help a starved
  proposer.
- `output execution task finished`, `output executed` and `persisted output` gave the F2 verdict: execute 165 → 87 µs/tx,
  persist 50 → 199. The MDBX commit fsync tripled with identical logical writes ({{ISSUE:persist-fsync-amplification}}).
- The warn and error census fell from 266,118 to 77,168 lines over a run of the same shape; 0 panics, 0 DB errors.

## Evidence (bench 4, run r20261105-0803)

Ten validators in ten GCP regions plus one observer ran this branch's image (pinned by digest) with consensus parameters
unchanged (1000/350/250 ms), through a 40-min mixed blast with the standard chaos plan: one validator SIGKILLed 60 s
before an epoch close and started 300 s later, then an observer restart. 4,578 tx/s with all generators running (+13.4 %
against bench 3 on v0.2.0-devnet), 12.31 M landed, land p50 / p95 / p99 3.30 / 12.84 / 31.4 s; 0 panics, 0 MDBX or RPC
errors. Report: https://benchmark.telcoin.network/runs/r20261105-0803/report.html.

One line per question:

- Q1 voter wait: under load the voter waits on its own execution (fleet `exec_wait` p95 930 ms, vote-lock p95 771 ms);
  parents, batches and lead stay at 0-1 ms; an idle vote takes 2 ms. The slow voters are the nodes with the deepest engine
  queue, not the farthest ones.
- Q2 proposer side: adds little. `header_age_ms` 1-3 ms, header persist p95 65-111 ms under load, retries on 0.2-0.6 % of
  requests.
- Q3 leader share: 94.7 % of 5,826 leader rounds committed; the two far validators lead 4 and 5 of 1,958 idle rounds
  (swapped out by reputation); 6.3 % of loaded leader rounds, and 14.4 % of those while two members were out, had no
  leader certificate.
- Q4 execution or persist: execution. Engine busy 976-988 ms/s on every node, queue at its cap of 8, execute 75 % and
  persist 24 % of each output (the MDBX commit, almost all fsync, is 70 % of the persist), about 215 µs/tx and flat. The
  persist no longer grows as it did in bench 3 (60-72 % of busy time, per-tx cost doubling).
- Q5 rejoin loop: still there. The restarted validator was promoted 13 times (12 fell back), a demoted one 21 times (20
  fell back), each from an empty restored DAG and a stale stored header; only an epoch entry held. Restart to rejoin
  2,168 s.
- Q6 batch starvation: none under load. The batch-serve pool never filled (`tn_worker_sync_serves_denied_total` 0 on all
  11); one 8-s burst of stream-open sheds at an epoch boundary.
- Q7 epoch-record quorum: every record reached quorum with 0 timeouts, but two were signed by exactly 7 of 10; the five
  `failed to reach quorum on epoch close` lines were false alarms (follow-up 2).
- Q8 V1Lazy (#1783): one round trip per vote (wire time / UDP RTT 1.00 over 72 pairs, request leg minus response leg
  0.00 RTT); idle round 352 ms, the 350-ms minimum (bench 3: 451 ms); all ten validators certify 99.6-100 % idle (bench 3:
  5 % on the two far ones); no `Io(Other)` and no `UnsupportedProtocols`.

Two systemic findings:

1. Healthy validators are demoted by their own commit lag. Under load two validators logged `we are behind, go to catchup
   mode! … reason=outside_gc_window` at exactly 41 rounds, mid-epoch, with no fault and no committee rotation. Their MDBX
   commit fsync p50 was 533 and 420 ms against 305-364 ms elsewhere, so their engine queue was longer (p95 15.3 and 14.5 s
   against 10.0-11.3 s) and their own Bullshark commit drifted 2-6 s a minute behind the fleet. The consensus task waits
   for local execution of each committed sub-DAG before it publishes the committed round (`consensus/state.rs:622, :682`),
   and `behind_consensus` counts that round (`network/handler.rs:202, :219`). The committee fell to eight voters, the chaos
   kill left exactly seven (the quorum), and commits paused for 17 s. Both came back only at an epoch entry (follow-ups 3
   and 4; {{ISSUE:f1-commit-lag-demotion}}).
2. Execution bounds throughput at about 215 µs per transaction: busy about 0.98 on every node, the queue at its cap, and
   chain throughput holding while the landing generators fell from ten to seven. Not separated: the pre-existing `engine`
   Debug dumps run on the execution thread under `engine=debug` (follow-up 1; {{ISSUE:f2-execution-ceiling}}).

### Which lines answered which question

Every finding above comes from the lines and series these commits add. None of the commits changes behaviour: log lines,
counters, histograms and the `leader_with_swap` wrappers only.

- Q1: `vote path timing` (`exec_wait_ms`, `lock_ms`, `persist_ms`, `total_ms`), `vote timeout fired` (stage), `vote
  refused: header too new` (7a9ac247e).
- Q2: `vote requests issued` (`header_age_ms`), `header stored and sent` (`persist_ms`), `Ok response received after
  request vote … attempt elapsed_ms` (8663c297b).
- Q3: `scheduled leader` (`swapped`, `found`), `leader=` on `subdag committed`, `tn_primary_leader_{rounds,commits}_total`
  (7725b8543).
- Q4: `output execution task finished` (`queue_wait_ms`, `task_ms`), `output executed` (`execute_ms`, `persist_ms`),
  `persisted output` (`save_blocks_ms`, `commit_ms`), `tn_engine_busy_milliseconds_total` (b539caf1c).
- Q5 and the demotion: `we are behind …` with `round effective_exec_round gc_window reason`,
  `tn_node_mode_transitions_total{to,reason}`, `rejoin not ready … reason`, `attempting to rejoin consensus …
  handled_round newest_round`, `dag restored num_certs`, `reproposing header … header_round primary_round` (d66ce4892).
- Q6: `tn_worker_sync_serves_denied_total{tier}`, `tn_worker_batch_requests_{denied,failed}_total` (8a92c088d).
- Q7: `epoch record quorum … signers timeouts missing=[…]`, the failure line's new fields, `tn_node_epoch_record_signers`
  (1374afa17).
- Q8: `network::reqres` `inbound request` / `response sent` (`service_ms`) and `response received` (`elapsed_ms`); wire
  time is the proposer's round trip minus the voter's `total_ms` (94b0d8cd9, 7a9ac247e).

Cost: with every target of the bench filter at debug a node wrote 7.3 MB/min idle; under load the non-`engine` targets
wrote about 3 MB/min. 99.7 % of the loaded bytes were the pre-existing `engine` dumps of follow-up 1, not lines from these
commits.

## Review notes

- Must be resolved before staging merges to main: `{peer}` label cardinality. `tn_worker_batch_requests_{denied,failed}_total{worker,peer}`
  labels any connected worker peer. That is bounded on a bench fleet (closed or trust-everywhere admission; 20 connections
  per node in bench 4) and unbounded on a public network. Restrict the label to committee members plus `peer="other"`.
  The outbound request histogram `tn_network_outbound_request_duration_seconds` is labelled by outcome and class only.
- Busy-ms truncation under-reads during replay of tiny outputs.
- `construct_dag_from_cert_store` still logs one untargeted info line per restored certificate (pre-existing).
- The Alloy relabel on nodes overwrites the node's own `network` label, so `tn_network_*{network}` series collide across
  primary and workers. That is observability config, not this PR.

## Follow-ups

1. Engine Debug dumps (pre-existing, not from these commits): `debug!(target: "engine", ?output, "executing output")`
   (`crates/engine/src/payload_builder.rs:74`), `debug!(target: "engine", ?next_canonical_block, "block executed")`
   (`:372`), and the per-transaction `governance collects` / `allocating basefees` (`crates/tn-reth/src/evm/handler.rs:132,
   :181`). Under `engine=debug` they wrote about 1.16 GB a minute per validator under load (about 716 kB per `block
   executed` line, 18.7 MB per `executing output`), a 49-GB unit log per validator in a 2-h run, and they are formatted on
   the execution thread. They share the `engine` target with the three engine lines added here, so no filter keeps one and
   drops the other. Fixed later in this stack by `perf(engine): demote the engine debug dumps to trace`
   ({{ISSUE:f2-execution-ceiling}}).
2. Epoch-record collector: a node that misses the first broadcast of its peers' votes sees `signers=1`, times out 25
   times, logs `failed to reach quorum on epoch close` at error after 64-65 s, and gets the record by peer fetch
   (`crates/node/src/manager/epoch_votes.rs:230-240`); three of the five such lines were on-time idle nodes. Re-request
   votes once, or log the fetched outcome at info and keep error for a failed fetch.
3. Promotion loop ({{ISSUE:f3-rejoin-loop}}): on a mid-epoch promotion the DAG is rebuilt from the certificate store with
   0 certificates (`consensus/state.rs:144, :171`), the proposer re-sends a stored header of an old round that every peer
   refuses as too old (`proposer.rs:866`), `exec_round` stays frozen, and `behind_consensus` demotes the node about 8 s
   later at +41 rounds; after a 60-s catch-up stall it promotes again (a cycle of about 71 s). Only an epoch entry within
   the first 20 rounds holds. The issue's proposal supersedes the one written after bench 4.
4. Demotion of a validator that is merely slow ({{ISSUE:f1-commit-lag-demotion}}): `behind_consensus`
   (`network/handler.rs:166-262`) demotes when an incoming round is more than `gc_activity_window` = gc_depth - 10 = 40
   rounds (`types/src/primary/mod.rs:72`) above `effective_exec_round`, whose `committed_round` term is published only
   after the execution wait (`consensus/state.rs:622, :682`). So a node whose engine is about 10 % slower per transaction
   (its fsync about 55 % slower) is demoted under sustained load, and with two such nodes and one fault the committee ran
   at exactly quorum. The issue's proposal supersedes the one written after bench 4.
5. Leader schedule names demoted members: `scheduled leader … found=false` (`consensus/bullshark.rs:331`) on 6.3 % of
   loaded leader rounds and 14.4 % while two members were out; the swap table learns nothing from a member's mode or its
   TooNew refusals. Swap out a member with no certificate for k rounds.

Observability gaps the run found: a debug line with the wait time at `consensus/state.rs:622` (where the commit drift
accumulates is inferred, not measured); the vote outcome `rejected` is a catch-all; the 15-s `tn_node_mode` gauge misses
promotions that last 7-9 s (use `tn_node_mode_transitions_total`).

Refs {{ISSUE:f1-commit-lag-demotion}}
Refs {{ISSUE:f3-rejoin-loop}}
