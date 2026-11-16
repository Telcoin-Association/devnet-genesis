## Summary

The epoch record collector can get past an epoch the network left uncertified, and vote rounds can certify it later (#1850), behind two switches, default off: `epoch_record_collect_past_uncertified` and `epoch_record_recertify`.
No switch: the serving peer on `retrieved cert` lines, the gauge `tn_state_sync.epoch_records_certified_through`, an info line for a false quorum error (#1852), an evidence line and a counter in front of main's stop on a conflicting certified record.
One behaviour changes with every switch off: a full vote queue never evicts the rounds of the newest record or the one before it.

PR 5 of 8 in the stack #1862 to #1869; #1862 targets `main`, this PR targets #1865's branch (`fix/epoch-record-closing-block-check`), so the Files tab shows this change alone (27 commits); the stack's base is main at 33b727fce.
The stack will be collapsed into #1862 (each PR merged into the branch below it); `main` is then merged into that branch and `make attest` runs on the result.
Please merge with 'Create a merge commit': a squash would leave the pull requests above this one with commits their base no longer has.

## Problem

On main at 33b727fce the collector ends each pass at the first epoch no peer serves (`crates/state-sync/src/epoch.rs:372-374`) and peers serve a record only with its certificate (`crates/consensus/primary/src/network/handler.rs:1909-1919`): an epoch K the network leaves uncertified stops every collector at K, across restarts.
The failsafe re-votes only the previous record, once (`crates/node/src/manager/epoch_votes.rs:483-502`), so K stays uncertified; a node fed only by the collector gets nothing past it.
No run reached this state, so it is inferred from code, not observed: all 37 closes of [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and r20261112-1520 (no public page) certified with at least 7 of 10 validators.
Since #1849 a certified record that conflicts with the node's own stops the node in the collector (`state-sync/src/epoch.rs:228-245`, counted in `tn_epoch.final_state_mismatches_total`), as the vote round's recovery does (`epoch_votes.rs:279-289`); the collector's line names the epoch and both digests, not who certified the other record or which peer served it.

A short round logs `failed to reach quorum on epoch close` at error without a store check (`epoch_votes.rs:231-237`): 11 times in those runs, each with the certificate already stored (#1852).

## Change

Observability, no switch:
- `bb5f2533e`: `request_epoch_cert` returns the answering peer too; both `retrieved cert` lines gain `peer` and `signers`.
- `9a401b658`: the gauge, the highest E with epochs 0..=E certified (-1 before epoch 0's), set at startup and after each collector pass.
- `053713719`: a short round whose certificate is held logs `epoch vote round ended without a local quorum; the record is already certified` (info), counts `tn_node.epoch_record_round_ended_certified_total`, sets `tn_node.epoch_record_signers` from that certificate, without the missing-certificate alarm; recovery unchanged.

Re-certify (`047910bcf`, doc `1dfa680a0`):
- `9e97158b9`: verified votes are kept per (epoch, digest) and seed the record's next round; each close N and the startup re-arm also re-vote one older own uncertified record, round-robin over epochs N-16 to N-2 (members only).
- Older records' rounds leave `tn_node.epoch_record_signers` alone and label missed signers `round=recertify` (`f2f3de1bd`, `3143a099d`); kept quorums are aggregated, never for a conflicting record (`80e1672a8`, `8c76745f2`).
- A conflict in a re-certify round ends as in any vote round on main: the recovery logs `… we have forked!` at error and stops the node (`818d61e47` pins it for a round this node picked or not, the previous record's round, and the switch off).

Walk (`df0075d98`, one switch):
- `b8142b234`: a peer's "not held" for an epoch this node closed and stored itself no longer ends the pass; the next record must validate against that own record, and the epoch becomes a gap (at most 16) retried until certified.
- Retries stop at 5 s or shutdown, a cut gap leads the next (`0a7c8f21c`, `8038aa198`); failed reads keep gaps (`352a78b9e`); a refusal after a walk still persists (`5b9c4f210`); a walk that did not land waits 5 s (`7d2639473`); docs `3805eab5b`, `4d3c7e7fb` (both also what a conflict does and how to read its counters).
- The walk does not change what a conflict does, but it reaches epochs past an uncertified one, so a node with it on can meet, and stop on, a conflict there that a node with it off never asks for.

Conflicting certified record, no switch (`b8142b234`, `4c63328ca`, `d6992db59`, doc `b7f008dc9`):
- Main's stop stays as it is, in the collector, its gap retry and the startup sync, with the walk on or off.
- Before it, the collection reads the committee the record before the epoch names, counts `tn_state_sync.epoch_record_conflicts_total` and logs at error (`epoch-manager`) `epoch record conflict: this node's stored record of epoch {epoch} differs from a record certified by {signers} of the {committee} members of the committee the record before it names; this node stops; do not delete its chain data before the cause is known` with `epoch`, `stored`, `offered`, `peer`, `signers`, `committee`, `signer_ids`, `offered_epoch`, `offered_parent`, `offered_final_number`, `offered_final_hash`.
- Main's line and `tn_epoch.final_state_mismatches_total` follow; the count, the line and the stop come after the read with no await between them, so a startup pass cut short during the read counts nothing; every restart stops the same way.
- Dropped from this change's earlier form: the switch `epoch_record_conflict_halt` with its threshold (`2n/3 + 1` of the committee the previous record names), its pre-flight and below-threshold counter, and the re-certify round's own conflict line and counter; since #1849 main stops on every such conflict, so this head adds only the evidence line and the counter.

Eviction, no switch (`ba73ee5f9`): a full vote queue drops rounds that ended, then evicts the lowest epoch's, never the newest two records'.

Hook and e2e: `8b3109ddb`, `64a6de4b5`: `TN_TEST_WITHHOLD_EPOCH_VOTE=<epoch>`, `TN_TEST_WITHHOLD_EPOCH_VOTE_ROUNDS=<n>` (default 1): no own vote in that record's first n rounds; off without `tn-types`' `test-utils`, which the release image's `-p telcoin-network` build lacks (a workspace-root build without `-p` has it, as with the existing fork-epoch hooks); `ff877fb0e`: `tests/it/epoch_record_walk.rs` and `tests/it/fleet.rs` (shared helpers).

## With every switch off

New work: a certified-prefix read per collector pass, a `cert_by_digest` read per short round, a copy of each downloaded record and certificate for its save, and per conflict a read of the previous record and the `epoch record conflict:` line before main's stop.
New output: `peer` and `signers` fields, switches on `node switches`, three state-sync counters, the gauge, the `tn_node.epoch_record_round_ended_certified_total` counter, a `round` label on missed signers (sums unchanged).
Behaviour: only the eviction, when a round is queued while five are (main evicts the oldest-queued entry, live or ended, `epoch_votes.rs:403-404`); it changes which of this node's rounds finish, and so which certificates it stores itself, not a block, state root, vote, signature or consensus pack byte.

Mixed fleet: no switch changes a message, a record digest, a vote or a certificate rule: one chain.
Nodes differ in which records they hold certified, and a node with the walk on can reach a conflict a node with it off never asks for; any node that meets one stops.
A switch-off member adds no new vote for an older record, so a re-certify round needs a switch-on node to hold a super-quorum from the votes it kept from earlier rounds (any member's) and the switch-on members' re-votes.

## Testing

Unit tests: `test_failed_round_with_a_held_cert_logs_info_and_counts`, `test_collect_epoch_records_walks_past_an_own_uncertified_epoch`, `test_collect_epoch_records_does_not_walk_past_a_missing_record`, `test_gap_retry_lets_go_at_its_deadline_and_on_shutdown`, `test_kept_quorum_of_two_short_rounds_is_aggregated`, `test_older_rounds_do_not_evict_the_latest_close`, `test_every_conflict_reaches_the_final_state_mismatch_stop`, `test_conflict_and_invalid_record_lines_carry_the_evidence`, `test_startup_sync_walks_under_the_switch_and_stops_on_a_conflict`, `test_a_conflict_cancelled_at_its_evidence_read_is_counted_once`, `test_recertify_round_stops_on_a_conflicting_record`.

On this head: `cargo nextest run --locked` of `tn-config`, `state-sync`, `tn-node`, `tn-primary`, `tn-types` and `tn-network-libp2p` 1,952 passed, 9 skipped, and clippy clean on `tn-config`, `state-sync`, `tn-node` and `tn-primary`, at `8c76745f2`; above it, `state-sync` and `tn-config` 228 passed and clippy clean at `d6992db59`, `state-sync` 78 passed at `b7f008dc9` (doc comments only); fmt clean.
Each of the 24 commits up to `8c76745f2` passed `cargo check --locked --all-targets -p tn-config -p state-sync -p tn-node -p tn-primary -p e2e-tests` with warnings denied; the two after it passed `cargo check` on the packages they touch.
The e2e commit on `8c76745f2` (this head's tree without `d6992db59` and `b7f008dc9`): e2e crate check, fmt, clippy clean; `epoch_record_walk.rs` 3 of 3 (two of four validators withhold their vote for epoch 1's record in its first two rounds; no node logs or counts a conflict).
Switches off, an observer holding that record collects nothing past it and closes no epoch after it comes back (`test_uncertified_epoch_stops_the_collector_with_every_switch_off`); with the walk, it and the validators walk past and it executes on, a fresh observer still stops (`test_uncertified_epoch_walked_past`); with re-certify, epoch 3's close certifies epoch 1 and both observers collect every record (`test_uncertified_epoch_recertified`).
Not run on a fleet; a benchmark of this stack's earlier cut on main at 45dce8947 is running, and this text reports none of its results.

Stack-wide gates ran before these PRs were opened, on the top of the full stack: `fix/1807-digest-order-hold` at `500e21afa`, 103 commits on main at 33b727fce, carries the code of all eight pull requests (#1862 to #1869).
- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.
- `./etc/ci-lanes.sh clippy`: passed.
- `cargo nextest run --locked --workspace`: 5,624 passed, 149 skipped.
- Every one of the 103 commits compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied).
- `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12 and `make test-e2e-resync` 1/1, once with every switch off and once with the full stack's six switches on.
- `make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time): passed with every switch off and with the six on.
- The 13 e2e tests the full stack adds, three runs each: all passed.
- The three `state_export_import` tests, which restore a node from an exported state: passed.
- Against a later main, c1b1eb9fe (#1859): the top merges without conflict, and the merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-storage` (1,764 passed, 21 skipped).
- Against the main of 2026-11-16, 0554efd4f (#1861): one file conflicts, `crates/node/src/manager/epoch_votes.rs`. #1861 renamed the collector's failure channel and ends a vote round on a forked record with an error; #1866 added the kept signatures to the same functions. In a local trial merge both changes are kept, the drop of a forked record's kept signatures moves in front of #1861's early return, and one test of #1866 expects the fork as an error. The merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-types -p tn-reth -p telcoin-network-cli` (2,175 passed, 17 skipped). The merge itself is made after the stack is collapsed.

## Limits and what a reviewer should look at

- The walk never helps a node without its own record (it cannot check that epoch's `next_committee`): a fresh observer still stops (tested); only re-certification reaches it.
  Not examined: consensus catch-up through an uncertified epoch; gossip of former members' votes.
- Argued from code, untested against faulty members: the walk accepts only what validates against the node's own record, and kept votes build no certificate one round with the same votes could not; bounds: 16 gaps, kept votes of 17 records, no receive-side lookback (as on main).
- The stop's signer bar is main's: validation accepts a super-quorum of the offered record's own committee, which may be a subset of at least four members and two thirds of the committee the previous record names (10 named, 7 in the record, 5 signers: more than f of the 10); whether the stop should need 7 of 10 is the question on #1850.
  On main at 33b727fce a node holding a record that conflicts with a certified one stops when its collector asks for that epoch, with or without this head; the walk adds the epochs past an uncertified one.
- Open: if the previous record cannot be read, the evidence line shows `committee=0` and no signer ids, and the node still stops; the stop skips the pass's persist, as main's does; the evidence's committee is read after the failed save.
- The evidence line covers the collection only: a vote round's stop keeps main's `we have forked!` line, with neither peer nor signers, and main does not count it in `tn_epoch.final_state_mismatches_total`.
- `recertify_older_record` logs a pick before marking it: for under a millisecond a pick is logged but uncounted.
- Upstream text this head leaves as it is, on main at 33b727fce: `crates/storage/README.md:427-429` still says a conflicting record from a peer "is only logged"; `crates/tn-reth/README.md:1270-1278` names main's stop line and counter, not the evidence line or `tn_state_sync_epoch_record_conflicts_total`.
- Some commits are corrected by later commits of this head rather than squashed (seven at least; `d6992db59`, for one, moves the conflict count of `4c63328ca` after its evidence read), and an e2e error message names `STACK_SWITCHES_ON`, which a later head adds.

## Related

- Refs #1850: its fix sketch for the uncertified epoch (the walk and re-certification behind default-off switches; the gauge and the serving peer always on, as the sketch asks); its stop on a conflicting certified record is on main since #1849, and this head adds the evidence line and the counter in front of it. Not `Fixes`: by default nodes still stop at an uncertified epoch, a node without the record needs re-certification, and its benchmark check has not run.
- Fixes #1852: every point of its sketch, including its open question: the gauge reports the held certificate's signers.
- Next: `fix/epoch-loop-output-drop` and `fix/1804-quorum-exec-block` build on this head.
