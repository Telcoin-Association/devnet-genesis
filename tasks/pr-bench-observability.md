# Draft PR (telcoin-network) — not yet opened; the bench-4 run (r20261105-0803) is done and the body below cites its results

Head (original): bench/main-v1lazy-obs-2026-11 @ 496ebefb5 (pushed), stacked on PR 1783. PR 1783 merged on 2026-11-05 (7527b15c0), so
the PR is no longer stacked: on 2026-11-06 the nine commits were cherry-picked (-x) onto bench/main-fixes-2026-11 (base origin/main
4bf4604d2) as 77539d77d e938be258 49643180d 4ab917aae 180a2d8c1 c6e8df6dd 2d47fe191 f7936def8 3a721a1b6 (clean; libp2p+primary
916 tests, the three PR-1783 tests, fmt and clippy green). To open the observability PR alone: `git switch -c feat/bench-observability
origin/main && git cherry-pick -x 77539d77d^..3a721a1b6` (or the original 94b0d8cd9^..496ebefb5), push over ssh, then:
gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head feat/bench-observability --title "<title>" --body-file <this file's body>
Compare URL (original branch): https://github.com/Telcoin-Association/telcoin-network/compare/main...bench/main-v1lazy-obs-2026-11
The per-commit bullets below cite the original shas; the ledger tasks/bench5-cherrypick-ledger.md maps them to the new ones.
## Title
feat: benchmark observability — vote path, persist, rejoin, leader, batch and epoch-record instrumentation

## Body (per-commit summary; observability only, no behaviour change, no new dependencies)
- 94b0d8cd9 feat(network): `tn_network_outbound_request_duration_seconds{outcome,class}` and `network::reqres` debug lines
  (`inbound request`, `response sent`, `response received`, `outbound request failed`) with peer, request_id, class and ms.
- 7a9ac247e feat(primary): the voter's vote path stamped by stage (lock, validate, exec_wait, parents, lead_sleep, sync_batches,
  vote_store, persist) → one `vote path timing` line per request, `tn_primary_vote_stage_seconds{stage}`, vote outcome counters,
  `vote timeout fired` with the stage in progress, explicit `vote refused: header too new`, header batch sync lines.
- 8663c297b feat(primary): proposer side — per-peer vote round trips on every response (round, attempt, elapsed_ms),
  `vote requests issued` (header_age_ms, peers), `proposal lock acquired` (lock_wait_ms), `header stored and sent`
  (read/write/persist/send ms).
- b539caf1c feat(engine): queue wait, busy milliseconds and persist duration on EngineMetrics; `output executed`
  (execute/persist/announce ms) and `persisted output` (open/save_blocks/markers/commit ms, accounts, storage slots) with
  `tn_reth_persist_*` series.
- d66ce4892 feat(subscriber): `tn_node_mode_transitions_total{to,reason}` at every demotion/promotion site, `RejoinBlocker`
  classification with throttled `rejoin not ready` lines and `tn_executor_rejoin_blocked_total{reason}`, round fields on the
  behind-consensus, rejoin and reproposing lines, `dag restored` span.
- 7725b8543 feat(primary): `scheduled leader` per decided leader round (swapped, found) + `tn_primary_leader_rounds_total`,
  `tn_primary_leader_commits_total{leader}`, leader named on `subdag committed`; `leader_with_swap` primitives.
- 8a92c088d feat(worker): `tn_worker_sync_serves_denied_total{worker,tier}`, `tn_worker_batch_requests_{denied,failed}_total{worker,peer}`,
  elapsed_ms on the pool-full denial line.
- 1374afa17 feat(epoch-manager): `epoch record quorum` with signers/committee/timeouts/missing=[ids], `tn_node_epoch_record_signers`,
  `tn_node_epoch_record_missing_signers_total{signer}`.
- 496ebefb5 fix(observability): sub-ms bucket layout for the vote-stage and queue-wait histograms (Full matchers), batch-sync
  abandon lines at debug, review follow-ups (watch borrow, lock-held increments, variant-order asserts).

Review notes to carry: `tn_worker_batch_requests_*{peer}` labels any connected worker peer — bounded on a bench fleet (closed or
trust-everywhere admission; 20 connections per node in bench 4),
unbounded on a public network → restrict to committee + `peer="other"` before merging to main. Busy-ms truncation under-reads during
replay of tiny outputs. `construct_dag_from_cert_store` still logs one untargeted info line per restored certificate (pre-existing).
The Alloy relabel on nodes overwrites the node's own `network` label, so `tn_network_*{network}` series collide across primary and
workers (observability config, not this PR).

## What bench 4 showed (r20261105-0803; full report: bench4-report-r20261105-0803.md)
Ten validators in ten GCP regions plus one observer ran this branch's image (pinned by digest), consensus parameters unchanged
(1000/350/250 ms), through a 40-min mixed blast with the standard chaos plan (one validator SIGKILLed 60 s before an epoch close and
started 300 s later, then an observer restart). 4,578 tx/s with all generators running (+13.4 % against bench 3 on v0.2.0-devnet),
12.31 M landed, land p50 / p95 / p99 3.30 / 12.84 / 31.4 s; 0 panics, 0 MDBX or RPC errors. One line per question:
- Q1 voter wait: under load the voter waits on its own execution (fleet `exec_wait` p95 930 ms, vote-lock p95 771 ms); parents,
  batches and lead stay at 0-1 ms; an idle vote takes 2 ms. The slow voters are the nodes with the deepest engine queue, not the
  farthest ones.
- Q2 proposer side: adds little: `header_age_ms` 1-3 ms, header persist p95 65-111 ms under load, retries on 0.2-0.6 % of requests.
- Q3 leader share: 94.7 % of 5,826 leader rounds committed; the two far validators lead 4 and 5 of 1,958 idle rounds (swapped out by
  reputation); 6.3 % of loaded leader rounds and 14.4 % of those while two members were out had no leader certificate.
- Q4 execution or persist: execution. Engine busy 976-988 ms/s on every node, queue at its cap of 8, execute 75 % and persist 24 % of
  each output (the MDBX commit, almost all fsync, is 70 % of the persist), about 215 µs/tx and flat; the persist no longer grows as
  it did in bench 3 (60-72 % of busy time, per-tx cost doubling).
- Q5 rejoin loop: still there. The restarted validator was promoted 13 times (12 fell back), a demoted one 21 times (20 fell back),
  each from an empty restored DAG and a stale stored header; only an epoch entry held. Restart to rejoin 2,168 s.
- Q6 batch starvation: none under load: the batch-serve pool never filled (`tn_worker_sync_serves_denied_total` 0 on all 11); one
  8-s burst of stream-open sheds at an epoch boundary.
- Q7 epoch-record quorum: every record reached quorum with 0 timeouts, but two were signed by exactly 7 of 10; the five `failed to
  reach quorum on epoch close` lines were false alarms (see follow-up 2).
- Q8 V1Lazy (PR 1783): one round trip per vote (wire time / UDP RTT 1.00 over 72 pairs, request-leg minus response-leg 0.00 RTT);
  idle round 352 ms, the 350-ms minimum (bench 3: 451 ms); all ten validators certify 99.6-100 % idle (bench 3: 5 % on the two far
  ones); no `Io(Other)` and no `UnsupportedProtocols`.

Two systemic findings:
1. Healthy validators are demoted by their own commit lag. Under load two validators logged `we are behind, go to catchup mode! …
   reason=outside_gc_window` at exactly 41 rounds, mid-epoch, with no fault and no committee rotation. Their MDBX commit fsync p50
   was 533 and 420 ms against 305-364 ms elsewhere, so their engine queue was longer (p95 15.3 and 14.5 s against 10.0-11.3 s) and
   their own Bullshark commit drifted 2-6 s a minute behind the fleet: the consensus task waits for local execution of each
   committed sub-DAG before it publishes the committed round (`consensus/state.rs:622, :682`), and `behind_consensus` counts that
   round (`network/handler.rs:202, :219`). The committee fell to eight voters; the chaos kill left exactly seven, the quorum, and
   commits paused for 17 s. Both came back only at an epoch entry (follow-ups 3 and 4).
2. Execution bounds throughput at about 215 µs per transaction: busy about 0.98 on every node, the queue at its cap, and chain
   throughput holding while the landing generators fell from ten to seven. Not separated: the pre-existing `engine` Debug dumps
   run on the execution thread under `engine=debug` (follow-up 1).

## What bench 5 showed (r20261107-1504; full report: bench5-report-r20261107-1504.md)

The same nine commits, cherry-picked onto origin/main 4bf4604d2, carried the bench-5 fix build. The lines were again the evidence:
- `vote path timing … outcome=behind exec_wait_ms=1001` on seven voters at once is how the F3-6 regression was found: the three
  fastest executors' headers were refused by every slower voter and certified 0.2 / 0.0 / 16.3 % of the time under load
  (tasks/issues/bench5-execution-behind-vote-starvation.md). The per-node refusal counts matched the counters within 1.5 %.
- `vote refused: header too new` fell from 100,852 lines (bench 4) to 12: the TooNew storm was a symptom of the commit-lag demotion.
- `header uncertified round= epoch= reason=` and `digests resent … cause=canceled` sized the cert-requeue change (2,811 of 2,813
  cancelled headers' digests landed in the next header, 113-118 ms later) and showed it cannot help a starved proposer.
- `output execution task finished` / `output executed` / `persisted output` gave the F2 verdict: execute 165 → 87 µs/tx, persist
  50 → 199 (the MDBX commit fsync tripled with identical logical writes; tasks/issues/bench5-persist-fsync-amplification.md).
- The warn+error census fell from 266,118 to 77,168 lines over a run of the same shape; 0 panics, 0 DB errors.

## The instrumentation was the evidence (no behaviour change)
Every finding above comes from the lines and series these commits add; none of the commits changes behaviour (log lines, counters,
histograms and the `leader_with_swap` wrappers only). The demotion and the promotion loop are origin/main behaviour that was
previously invisible: `we are behind, go to catchup mode!` and `failed to reach quorum on epoch close` predate the branch, without
the fields that now name the cause.
- Q1: `vote path timing` (`exec_wait_ms`, `lock_ms`, `persist_ms`, `total_ms`), `vote timeout fired` (stage), `vote refused: header
  too new` (7a9ac247e).
- Q2: `vote requests issued` (`header_age_ms`), `header stored and sent` (`persist_ms`), `Ok response received after request vote …
  attempt elapsed_ms` (8663c297b).
- Q3: `scheduled leader` (`swapped`, `found`), `leader=` on `subdag committed`, `tn_primary_leader_{rounds,commits}_total` (7725b8543).
- Q4: `output execution task finished` (`queue_wait_ms`, `task_ms`), `output executed` (`execute_ms`, `persist_ms`), `persisted
  output` (`save_blocks_ms`, `commit_ms`), `tn_engine_busy_milliseconds_total` (b539caf1c).
- Q5 and the demotion: `we are behind …` with `round effective_exec_round gc_window reason`, `tn_node_mode_transitions_total{to,reason}`,
  `rejoin not ready … reason`, `attempting to rejoin consensus … handled_round newest_round`, `dag restored num_certs`, `reproposing
  header … header_round primary_round` (d66ce4892).
- Q6: `tn_worker_sync_serves_denied_total{tier}`, `tn_worker_batch_requests_{denied,failed}_total` (8a92c088d).
- Q7: `epoch record quorum … signers timeouts missing=[…]`, the failure line's new fields, `tn_node_epoch_record_signers`
  (1374afa17).
- Q8: `network::reqres` `inbound request` / `response sent` (`service_ms`) and `response received` (`elapsed_ms`); wire time = the
  proposer's round trip minus the voter's `total_ms` (94b0d8cd9, 7a9ac247e).
Cost: with every target of the bench filter at debug a node wrote 7.3 MB/min idle; under load the non-`engine` targets wrote about
3 MB/min. 99.7 % of the loaded bytes were the pre-existing `engine` dumps of follow-up 1, not lines from these commits.

## Follow-ups this PR should carry or open as issues
1. Engine Debug dumps (pre-existing, not from this branch): `debug!(target: "engine", ?output, "executing output")`
   (`crates/engine/src/payload_builder.rs:74`), `debug!(target: "engine", ?next_canonical_block, "block executed")` (`:372`), and the
   per-transaction `governance collects` / `allocating basefees` (`crates/tn-reth/src/evm/handler.rs:132, :181`). Under `engine=debug`
   they wrote about 1.16 GB a minute per validator under load (about 716 kB per `block executed` line, 18.7 MB per `executing output`),
   a 49-GB unit log per validator in a 2-h run, and they are formatted on the execution thread. They share the `engine` target with
   this branch's three engine lines, so no filter keeps one and drops the other. Move them to `trace!` or to their own target.
2. Epoch-record collector: a node that misses the first broadcast of its peers' votes sees `signers=1`, times out 25 times, logs
   `failed to reach quorum on epoch close` at error after 64-65 s, and gets the record by peer fetch (`crates/node/src/manager/
   epoch_votes.rs:230-240`); three of the five such lines were on-time idle nodes. Re-request votes once, or log the fetched outcome
   at info and keep error for a failed fetch.
3. Promotion loop: on a mid-epoch promotion the DAG is rebuilt from the certificate store with 0 certificates
   (`consensus/state.rs:144, :171`), the proposer re-sends a stored header of an old round that every peer refuses as too old
   (`proposer.rs:866`), `exec_round` stays frozen, and `behind_consensus` demotes the node about 8 s later at +41 rounds; a 60-s
   catch-up stall later it promotes again (a cycle of about 71 s). Only an epoch entry within the first 20 rounds holds. Proposal:
   promote only with a quorum of certificates within the rejoin window (or write the followed outputs' certificates to the store),
   seed `primary_round` from the newest known header, a demotion grace after a promotion, and back off to the next boundary after
   two failed promotions.
4. Demotion of a validator that is merely slow: `behind_consensus` (`network/handler.rs:166-262`) demotes when an incoming round is
   more than `gc_activity_window` = gc_depth - 10 = 40 rounds (`types/src/primary/mod.rs:72`) above `effective_exec_round`, whose
   `committed_round` term is published only after the execution wait (`consensus/state.rs:622, :682`). So a node whose engine is
   about 10 % slower per transaction (its fsync about 55 % slower) is demoted under sustained load, and with two such and one fault the
   committee ran at exactly quorum. Proposal: base the activity check on consensus progress (commit before the execution wait, with
   a bound), and meanwhile a demotion grace and the engine queue depth on the warn line.
5. Leader schedule names demoted members: `scheduled leader … found=false` (`consensus/bullshark.rs:331`) on 6.3 % of loaded leader
   rounds and 14.4 % while two members were out; the swap table learns nothing from a member's mode or its TooNew refusals. Swap out a
   member with no certificate for k rounds.
Observability gaps for this branch, found by the run: a debug line with the wait time at `consensus/state.rs:622` (where the commit
drift accumulates is inferred, not measured); the vote outcome `rejected` is a catch-all; the 15-s `tn_node_mode` gauge misses
promotions that last 7-9 s (use `tn_node_mode_transitions_total`).
