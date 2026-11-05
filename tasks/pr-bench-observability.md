# Draft PR (telcoin-network) — not yet opened; opened after the bench-4 run so the body can cite its results

Head: bench/main-v1lazy-obs-2026-11 @ 496ebefb5 (pushed). Base: main. Stacked on PR 1783 (fix/libp2p-lazy-protocol-negotiation,
a4e55c880 dc1ad5f1d bbd0880ef e6d85bd68). Compare URL:
https://github.com/Telcoin-Association/telcoin-network/compare/main...bench/main-v1lazy-obs-2026-11
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head bench/main-v1lazy-obs-2026-11 --title "<title>" --body-file <this file's body>

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

Review notes to carry: `tn_worker_batch_requests_*{peer}` labels any connected worker peer — bounded under closed admission (bench),
unbounded on a public network → restrict to committee + `peer="other"` before merging to main. Busy-ms truncation under-reads during
replay of tiny outputs. `construct_dag_from_cert_store` still logs one untargeted info line per restored certificate (pre-existing).
The Alloy relabel on nodes overwrites the node's own `network` label, so `tn_network_*{network}` series collide across primary and
workers (observability config, not this PR).

## Questions Q1-Q8 (fill from the bench-4 run)
TBD after r20261105-0036 (or its successor) completes.
