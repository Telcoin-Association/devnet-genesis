## Summary

The epoch record collector can get past an epoch the network left uncertified, and vote rounds can certify it later (#1850), behind three switches, default off: `epoch_record_collect_past_uncertified`, `epoch_record_recertify` and `epoch_record_conflict_halt`.
No switch: the serving peer on `retrieved cert` lines, the gauge `tn_state_sync.epoch_records_certified_through`, an info line for a false quorum error (#1852), an eviction sparing the newest vote rounds.

PR 5 of 5 into `staging/benchmark-bench6-2026-11` (merge order: 00, 01, 02, 03, 04).
Stacked on `fix/epoch-record-closing-block-check`: this head contains its commits, so the Files tab shows them until that PR merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/1e38f1882fdb7d96c85db6294b4080ad9d14302e...065ee9e5a920f0e6b6d54a23cf4c1fa6cbbb78d4 (28 commits).
Please merge with 'Create a merge commit' so the next PR's diff collapses.

## Problem

On main at 45dce8947 the collector ends each pass at the first record it cannot store (`crates/state-sync/src/epoch.rs:343-345`) and peers serve a record only with its certificate (`crates/consensus/primary/src/network/handler.rs:1909-1919`): an epoch K the network leaves uncertified stops every collector at K, across restarts.
The failsafe re-votes only the previous record, once (`crates/node/src/manager/epoch_votes.rs:483-502`), so K stays uncertified; a node fed only by the collector gets nothing past it.
A conflicting certified record is only logged (`state-sync/src/epoch.rs:279`), though the vote round's recovery stops the node on it (`epoch_votes.rs:279-289`).
Inferred from code, not observed: all 37 closes of [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and r20261112-1520 (no public page) certified with at least 7 of 10 validators.

A short round logs `failed to reach quorum on epoch close` at error without a store check (`epoch_votes.rs:231-237`): 11 times in those runs, each with the certificate already stored (#1852).

## Change

Observability, no switch:
- `f41df0b3b`: `request_epoch_cert` returns the answering peer too; both `retrieved cert` lines gain `peer` and `signers`.
- `9bf27f194`: the gauge, the highest E with epochs 0..=E certified (-1 before epoch 0's), set at startup and after each collector pass.
- `1f04e4025`: a short round whose certificate is held logs `epoch vote round ended without a local quorum; the record is already certified` (info), counts `tn_node.epoch_record_round_ended_certified_total`, sets `tn_node.epoch_record_signers` from that certificate, without the missing-certificate alarm; recovery unchanged.

Re-certify (`f04b6bad9`, doc `7da885df5`):
- `818de6da4`: verified votes are kept per (epoch, digest) and seed the record's next round; each close N and the startup re-arm also re-vote one older own uncertified record, round-robin over epochs N-16 to N-2 (members only).
- Older records' rounds leave `tn_node.epoch_record_signers` alone and label missed signers `round=recertify` (`655f2cd1d`, `b9c02e003`); kept quorums are aggregated, never for a conflicting record (`16cf804e3`, `56ccf9920`); a re-certify conflict stops the node only with the halt on, at its threshold, else logs `own epoch record differs from a certified record in a re-certify round`, counting `tn_node.epoch_record_round_conflicts_total{round}` (`76d5ea885`); the newest two records keep main's stop.

Walk (`ea95ad288`, both collector switches):
- `5c9803f16`: a peer's "not held" for an epoch this node closed and stored itself no longer ends the pass; the next record must validate against that own record, and the epoch becomes a gap (at most 16) retried until certified.
- Retries stop at 5 s or shutdown, a cut gap leads the next (`d557046a9`, `9f20217e6`); failed reads keep gaps (`a129c7d4c`); a refusal after a walk still persists (`178b039c9`); a walk that did not land waits 5 s (`a7e2efbff`); docs `7673797b0`, `e28c5ee1b`.

Conflict halt (first in `5c9803f16`):
- Only `2n/3 + 1` signers of the `n` members the previous record names (7 of 10) stop the node, not the 5 of 10 validation accepts after an ejection (`028d4a4d0`); evidence, wording, doc: `38d9ab151`, `4357e0768`, `28ba6128d`.
- It logs at error (`epoch-manager`) `epoch record conflict halt: this node's stored record of epoch {epoch} differs from a record certified by {signers} of the {committee} members of the committee the record before it names; this node stops; do not delete its chain data before the cause is known` with `epoch`, `stored`, `offered`, `peer`, `signers`, `committee`, `signer_ids`, `offered_epoch`, `offered_parent`, `offered_final_number`, `offered_final_hash`, `halt_threshold`, `conflict_halt`, counts `tn_state_sync.epoch_record_conflicts_total`, and stops the node; every restart fails the same way.
- Recovery: switch it off and restart: the node logs `epoch record conflict: … this node keeps its own record`, counts it and runs on, as on main.
- Pre-flight (the switch's doc), with it off: if that counter exceeds `tn_state_sync.epoch_record_conflicts_below_halt_threshold_total`, the node would stop; grep logs for both conflict lines; flip one node at a time.

Eviction, no switch (`04ace8cd3`): a full vote queue drops ended rounds, then evicts the lowest epoch's, never the newest two records'.

Hook and e2e: `91ed3b450`, `ba28cb582`: `TN_TEST_WITHHOLD_EPOCH_VOTE=<epoch>`, `TN_TEST_WITHHOLD_EPOCH_VOTE_ROUNDS=<n>` (default 1): no own vote in that record's first n rounds; off without `tn-types`' `test-utils`, which release builds lack; `065ee9e5a`: `tests/it/epoch_record_walk.rs` and `tests/it/fleet.rs` (shared helpers).

## With every switch off

New work: a certified-prefix read per collector pass, a `cert_by_digest` read per short round, and per conflict a committee read and the `epoch record conflict:` line before main's handling.
New output: `peer` and `signers` fields, switches on `node switches`, four state-sync counters, the gauge, two `tn_node` counters, a `round` label on missed signers (sums unchanged).
Behaviour: only the eviction, when a round is queued while five are (main evicted the oldest-queued entry, live or ended).

Mixed fleet: no switch changes a message, a record digest, a vote or a certificate rule: one chain.
Nodes differ only in which records they hold certified and who halts; re-certifying needs a super-quorum of switch-on members.

## Testing

Unit tests: `test_failed_round_with_a_held_cert_logs_info_and_counts`, `test_collect_epoch_records_walks_past_an_own_uncertified_epoch`, `test_collect_epoch_records_does_not_walk_past_a_missing_record`, `test_gap_retry_lets_go_at_its_deadline_and_on_shutdown`, `test_conflict_halt_needs_a_super_quorum_of_the_full_committee`, `test_kept_quorum_of_two_short_rounds_is_aggregated`, `test_recertify_conflict_with_the_halt_off_does_not_stop`, `test_older_rounds_do_not_evict_the_latest_close`.

On e5121e7e1 (this head but for doc comments, README text and e2e files): `cargo check --locked --all-targets` exit 0, `cargo nextest run --locked --no-fail-fast` 1,340 passed, 7 skipped, `-p tn-node -p state-sync -p tn-config -p tn-types -p tn-primary`.
On this head: e2e crate check, fmt, clippy clean; `epoch_record_walk.rs` 3 of 3 (two of four validators withhold their vote for epoch 1's record in its first two rounds).
Switches off, an observer holding that record collects nothing past it and closes no epoch (`test_uncertified_epoch_stops_the_collector_with_every_switch_off`); with the walk, it and the validators walk past and it executes on, a fresh observer still stops (`test_uncertified_epoch_walked_past`); with re-certify, epoch 3's close certifies epoch 1 and both observers collect every record (`test_uncertified_epoch_recertified`).
A later head's test (`fix/1804-quorum-exec-block`) certified a missed record from kept votes 7.7-8.5 s after its members returned.
Not run on a fleet; the next benchmark runs all three switches on eleven nodes.

Stack-wide gates: run on the top of the stack before these PRs were opened; results in the stack's last PR.

## Limits and what a reviewer should look at

- The walk never helps a node without its own record (it cannot check that epoch's `next_committee`): a fresh observer still stops (tested); only re-certification reaches it. Not examined: consensus catch-up through an uncertified epoch; gossip of former members' votes.
- Argued from code, untested against faulty members: the walk accepts only what validates against the node's own record, kept votes build no certificate one round with the same votes could not, and at most f faulty members cannot reach the halt threshold; bounds: 16 gaps, kept votes of 17 records, no receive-side lookback (as on main).
- Turning the halt on stops a node already holding a conflict: hence the pre-flight. Open: a failed committee read counts as below the threshold (the pre-flight misses it); the halt skips the pass's persist; the threshold's committee is read after the save.
- `recertify_older_record` logs a pick before marking it: for under a millisecond a pick is logged but uncounted.
- Besides the open items above, nothing found before opening this PR is left unfixed.

## Related

- Refs #1850: every point of its fix sketch, behind default-off switches; not `Fixes`: by default nodes still stop at an uncertified epoch, a node without the record needs re-certification, and its benchmark check has not run.
- Fixes #1852: every point of its sketch, including its open question: the gauge reports the held certificate's signers.
- Next: `fix/epoch-loop-output-drop` and `fix/1804-quorum-exec-block` build on this head.
