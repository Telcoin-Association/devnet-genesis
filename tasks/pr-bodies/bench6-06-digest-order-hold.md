## Summary

Adds the own-chain order hold for #1807 behind the runtime switch `digest_order_hold` (default `false`; in this PR's diff the default keeps the base's drain).
With it on, a validator's next own header leaves queued every digest of a worker named in an older own header that the new header's parents do not prove to be on its own chain, until that older header commits, is canceled or re-queued, or the epoch ends.
Header validity, the messages and what peers vote for do not change; the header trigger still counts held digests, so at light load a held backlog can build a header earlier (see Limits).
Every node, switch on or off, counts digests re-queued out of order, what the orphan re-pool does with each transaction and dropped cancel reports, and logs its own parent on `header proposed`.

{{pr-09}}, the last PR of the stack, removes the switch and makes the hold the node's behaviour; once {{pr-09}} is merged into #1862's branch there is no switch.

PR 8 of 9 in the stack #1862 to {{pr-09}}; it was merged into #1868's branch (`fix/1804-quorum-exec-block`) on 2026-11-16, when the stack was collapsed into #1862, and its Files tab shows this change alone (17 commits).
#1862 now holds the stack's eight changes and targets `main`; {{pr-09}} targets #1862's branch and removes the switches; once it is merged, `main` is merged into that branch and `make attest` runs on the result.

## Problem

On main at 33b727fce the proposer drains each worker's digests first in, first out into its next own header (`crates/consensus/primary/src/proposer.rs:974`), and two paths put a dead own header's digests back at the front of their worker's queue: the cancel report of a header that will never be certified (`:902`) and the commit path for own headers an own commit skipped (`:823`, the walk at `:849`).
When a newer own header already carried the same worker's next digests, the older batch executes after the newer one, so a sender's later nonces run first, are skipped as `nonce_too_high`, and must be sent again.
Bench 6 measured the cost in the load blast at 20,000 IOPS: outside the generator whose validator was killed, senders gap-resent 29,449 transactions in [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) (always-on vote form) and 104,168 in [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) (adaptive), the nodes counted 13,036 and 52,588 `nonce_too_high` skips, and every gap-resend second fell 280-345 s after a lost own header of the generator's own validator (31 of 31 seconds, 124 of 124).
The ordering is read from the code; bench 6's link between resends and lost headers is a timing correlation; the model test and the e2e control below reproduce the reordering with the switch off.

## Change

- `fa48e098d` test(primary): hold a validator's own certificate on demand: `TN_TEST_OWN_CERT_DELAY_MS`, `_STAGE` and `_EVERY` (`tn_types::test_hooks::own_cert_delay`) hold an own certificate before it is stored (a newer own header cancels it) or after (it certifies too late to be a parent); unset, nothing is held.
- `bd655ff17` feat(primary): count dropped uncertified own header reports: `tn_primary_uncertified_report_dropped_total{reason}` (`shutdown`, `full`, `unsubscribed`) and one debug line.
- `83d68423c` feat(node): count what the orphan re-pool does with each transaction: `tn_node_orphan_txs_total{result}`, `tn_node_orphan_batches_total{path}` and counts on the `Finished processing orphaned batches` line; what is re-pooled and in what order is unchanged.
- `2d14d37b7` feat(tn-reth): re-export the pool's error kind.
- `f5ad6de5a` feat(node): split the orphan re-pool's refusals by the pool's error kind: `already_pooled`, `refused_nonce_too_low`, `refused_other`; only the last can be a loss.
- `98c41f45f` feat(primary): add the own-chain order hold rule for batch digests: `OwnChainOrder` in `order_hold.rs`, pure (no I/O, clock or logging), unused by the proposer yet.
- `11fd5bc00` test(primary): model the own-chain order hold against one author's proposer: a proptest model under random certification, cancels, dropped reports, commits with notice lag, re-sends and restarts.
- `2a63f2f67` test(primary): pin the proposer's payload order through both re-queue paths: a golden list taken from the code before the next commits.
- `9235cd25f` feat(primary): count batch digests re-queued out of order: per-worker numbers kept across re-queues, `tn_primary_requeued_out_of_order_total{cause}`, `tn_primary_requeued_order_unknown_total{reason}` and `out_of_order` on `digests resent`.
- `e546b2d7b` feat(primary): report the own parent and the order hold on header proposed: `own_parent`, `held`, `held_lanes`, `blockers`.
- `2ef50e6b5` feat(primary): log what the proposer leaves when it stops: `proposer stopped` with the queued digests and the uncommitted own headers.
- `b3e1b9c11` fix(primary): release a stale re-send's digest numbers: fixes the bookkeeping of `9235cd25f` when a commit notice is handled before the proposal result.
- `a4df4070b` feat(config): add the digest_order_hold switch: default `false`.
- `a9376d717` feat(primary): hold a worker lane behind an unproven older own header: the rule below, applied at the drain.
- `228743595` docs(primary): say what the order hold changes besides header contents: the trigger, and what releases a lane after a restart re-send or a dropped cancel report.
- `6f43811fb` docs(worker): say that the batch ledger's age-out can drop batches that still commit: a held digest keeps its slot in each peer's bound (#1794) until it commits.
- `500e21afa` test(e2e): the own-chain hold keeps every accepted transaction while a validator's chain breaks: the four tests below.

The rule (`order_hold.rs:10-37`): the new header at round n has an own parent when its parents hold this node's certificate of the tracked own header at n-1.
Its blockers are the tracked own headers below n that carry digests and are not proven own-chain ancestors of it ("tracked": built, neither committed nor re-queued).
It drains no digest of a worker named in a blocker's payload; those stay queued, in order (`proposer.rs:1404-1428`, `:1290`).
Consensus orders an older own header before a newer one or never, so a lane can only be reordered through a re-queue, and the hold keeps the lane until a commit notice or cancel report settles the older header (`order_hold.rs:51-60`).
The one residual is a garbage-collection cut below the leader: counted, not prevented (`:78-81`).

## The switch, and where it goes

In this PR's diff, with the switch off, the proposer never consults the hold (`order_hold.rs:46-47`): `order_hold` is `None` (`proposer.rs:409`) and the drain is the one over no held lane (`:1237-1239`), so header contents and timing are the base's.
New with it off, in this diff: per-worker digest numbers judged at each re-queue, the five counters above, `out_of_order` on `digests resent`, `own_parent` on `header proposed` with `held`, `held_lanes` and `blockers` at 0, the `proposer stopped` line, and `digest_order_hold=false` on the `node switches` line.
Only with it on do `tn_primary_headers_held_total` and `tn_primary_digests_held` move, does an out-of-order re-queue log a warning, and is a committed header that returns after its own commit notice left untracked (`proposer.rs:1511`).

{{pr-09}}, the last PR of the stack, removes the switch and the drain without the hold, so once {{pr-09}} is merged into #1862's branch there is no switch and no off state.
A reviewer should read the hold as unconditional: after {{pr-09}} every proposer applies the rule above at every drain, and the limits say what that changes against main.

In this PR's diff a mixed fleet is one chain: the switch changes only which queued digests a node puts into its own header, which no other validator checks.
After {{pr-09}} the same holds for main beside the stack during a rolling upgrade, and `make test-upgrade` with main as the previous binary passed on the stack's top with the six switches on (see the gates below).

## Testing

In `crates/consensus/primary/src/tests/order_hold_model.rs`, the model drives the real `OwnChainOrder`: with the hold on, `p1_each_lane_executes_in_order`, `p2_no_digest_executes_twice`, `p3_every_digest_is_accounted_for`, `p4_healthy_rounds_release_every_lane`, `p5_an_intact_chain_costs_nothing` and `gc_cut_is_the_only_overtake`; with it off, `hold_off_model_finds_the_overtake`; and both ways, `canceled_story_overtakes_only_without_the_hold` (a canceled header's digest overtakes without the hold and not with it).
In `crates/consensus/primary/src/tests/proposer_tests.rs`: `test_digest_order_bookkeeping_keeps_payloads_golden` (every header's payload through a cancel, two commit re-queues, a lane rotation and the header cap), `test_canceled_requeue_behind_a_newer_digest_counts_out_of_order`, `test_committed_requeue_behind_a_committed_digest_counts_out_of_order`, `test_order_hold_keeps_a_canceled_headers_lane_in_order`, `test_order_hold_holds_nothing_on_an_intact_own_chain` and `test_order_hold_replays_the_model_counterexample`.

In `crates/e2e-tests/tests/it/digest_order_hold.rs`, four validators run as processes and the hook holds one validator's own certificates, so its header at a held round is not a parent of its next one.
`test_hold_keeps_every_transaction_adaptive`, `test_hold_keeps_every_transaction_always` and `test_hold_survives_a_kill_of_the_far_validator` assert that every accepted transaction is in exactly one block with no resend, the out-of-order counter and the `nonce_too_high` skips are 0 on every node, and the hold ran (`tn_primary_headers_held_total` > 0).
The control, `test_without_the_hold_the_far_validator_reorders`, runs the same fleet with only `digest_order_hold` off and asserts that the hooked validator re-queued out of order and held nothing; the transactions it loses are reported, not asserted.
{{pr-09}} deletes the proposer tests that drive the drain without the hold (`test_digest_order_bookkeeping_keeps_payloads_golden`, the two `…_counts_out_of_order` tests, `test_stale_resend_requeue_is_not_out_of_order` and `test_stale_resend_releases_its_digest_numbers`) and the control; `test_order_hold_keeps_a_canceled_headers_lane_in_order`, `test_order_hold_holds_nothing_on_an_intact_own_chain` and `test_order_hold_replays_the_model_counterexample` stay, and so do the model's tests with the hold off, which flip the model's own flag and never read the node's configuration.
The two e2e tests named after a vote form are renamed after the hook stage they use.

On main at 33b727fce, at this head's tip `500e21afa`:
- Each of the 17 commits: `cargo check --locked --all-targets -p tn-config -p tn-types -p tn-primary -p tn-node -p state-sync -p e2e-tests`, no warnings.
- `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-types -p tn-primary -p tn-node -p state-sync`: 1,452 passed, 8 skipped.
- `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-config -p tn-primary -p tn-node -p e2e-tests -- -D warnings`: clean.

Bench 7 ran this head's node logic, on an earlier cut of the stack on main at 45dce8947, with the switch on: [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/) (always-on vote form) and [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/) (adaptive), ten validators at 20,000 IOPS, one run each, validator-05 killed in the load blast by design.
In the load blast, outside generator 05, neither run had a gap resend, an unlanded transaction after the 180-s tail scan or a `nonce_too_high` skip, against bench 6's 29,449 and 104,168 resends (counted from the load blast's warm-up start to its cool-down end), 0 and 9,290 unlanded and 13,036 and 52,588 skips.
Lost own headers carrying batches still occurred on all nine validators other than 05 (r20261115-1131: 981 not certified and 293 certified but never committed, none of them validator-05's; r20261115-1653 without validator-05's own: 988 and 338), and no gap resend followed any of them.
The exception is r20261115-1131's second light blast: one gap episode of 4 transactions on generator 06, whose resend second fell 280-345 s after a lost own header of validator-06, bench 6's pattern, and 22 `nonce_too_high` skips (2 per node on 11 nodes), where r20261115-1653 counted none.

This does not isolate the hold.
The storage engine (tn-lmdb), the vote path (the upstream vote-handler rework) and the run's shape (the kill earlier into the load; bench 6 began its load blast with transactions queued) changed with it, so the fall in resends, unlanded transactions and skips is not separable between them.
The one counter that isolates the hold, `tn_primary_requeued_out_of_order_total`, read 0 in both runs; it has no bench 6 twin and says no re-queue went out of order, not how many would have without the hold.
Bench 7 is consistent with the hold doing its job and does not prove it; the e2e tests and the model are the proof of the mechanism.

The hold's cost in the load blast, one run each, no spread:

| | r20261115-1131 | r20261115-1653 |
|---|---|---|
| Headers held | 1,866 | 3,259 |
| Held headers that carried a batch | 0 | 0 |
| Longest held run, headers (window) | 21 (before the kill) | 113 (after validator-05's start) |
| Longest held run, s (window) | 9.1 (after validator-05's start) | 55.3 (after validator-05's start) |
| Headers that created a blocker, fleet / validator-06 | 2.46 % / 6.9 % | 3.13 % / 15.6 % |
| Certified share, held headers / the rest | 49.8 % / 97.3 % | 60.5 % / 97.4 % |
| Over-quota batch reports | 0 | 0 |

Each validator runs one worker, so a held header carries no batch.
Each longest run is validator-06's maximum in the window named; r20261115-1131's two come from different windows, and the windows differ in length (before the kill 817 s and 1,121 s, after validator-05's start 1,308 s and 990 s), so a row compares two runs only where its windows match.
Held headers certified less often than the rest in both runs; that is an association, and no counter says the hold caused it.

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
- Against the main of 2026-11-16, 0554efd4f (#1861): one file conflicts, `crates/node/src/manager/epoch_votes.rs`. #1861 renamed the collector's failure channel and ends a vote round on a forked record with an error; #1866 added the kept signatures to the same functions. In a local trial merge both changes are kept, the drop of a forked record's kept signatures moves in front of #1861's early return, and one test of #1866 expects the fork as an error. The merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-types -p tn-reth -p telcoin-network-cli` (2,175 passed, 17 skipped). The merge itself is made once {{pr-09}} is merged.
- The order hold's model test's long hunt, `TN_ORDER_HOLD_HUNT_CASES=100000 cargo nextest run --locked -p tn-primary --run-ignored only -E 'test(=order_hold::model::long_hunt_order_hold)'`: 100,000 cases (seed 1223617546), no schedule breaks the rule.
- The stack's top is now {{pr-09}}, which removes the switches; the gates of that head are listed in its text.

## Limits and what a reviewer should look at

- Held digests count toward the digest trigger (`pending_digests_len`, `proposer.rs:1224-1226`, `:1715`), so a held backlog of at least `header_num_of_batches_threshold` builds the next header without the min delay, and that header can carry none of it.
  Bench 7 counted 152 and 183 early-trigger candidates among 1,110 and 2,056 held headers built on the digest trigger; these are inferred from logged fields, not measured, because `pending_before` on `header proposed` counts every lane, held ones included.
  A field with the un-held count on that line would measure it.
  The fleet ran a digest threshold of 5 and a minimum header delay of 350 ms.
- The narrower trigger (leave held digests out while the only blocker is the previous round's own header) is not built, and neither is a bounded wait for the own certificate.
- The plan's check "headers held where headers were lost" failed once per run: r20261115-1131's validator-06 during validator-05's outage (1 blocker created, 0 held headers), and r20261115-1653's validator-05 in the first light blast (18 blockers; none of its 26 headers with blockers had a pending queue, a batch or a held digest, so nothing was queued to hold).
- The far validators' batches are a separate defect: every batch-carrying header of validator-02 and validator-06 was certified in both light blasts of both runs, 46 to 76 % were never committed, and their digests were re-queued on the commit path a median 50 to 61 rounds later (21.0 to 21.4 s in r20261115-1653).
  The hold held none of their headers in those blasts, and bench 6, which had no hold, shows the same pattern in its first light blast.
- A held lane waits for the next own commit after a restart re-send of an already committed header, and behind an own header the certifier gives up on without a report (`order_hold.rs:105-115`); the base's digests wait as long there.
- No test aims at the hold's two known gaps on a running node: a garbage-collection cut below the leader (counted, not prevented; the model's `gc_cut_is_the_only_overtake` covers it) and the wait after a re-send after a restart (the item above; `test_hold_survives_a_kill_of_the_far_validator` restarts the hooked validator under load and asserts that no transaction is lost, not that wait).
- After {{pr-09}} every proposer applies the hold: the next header carries no digest of a worker named in an older own header that its parents do not prove to be on its own chain, until that older header commits, is canceled or re-queued, or the epoch ends; main drains every worker's queue first in, first out, one digest per worker in turn up to `max_header_num_of_batches`, whatever its older own headers carry.
- {{pr-09}} deletes the e2e control, `test_without_the_hold_the_far_validator_reorders`; after it the defect is shown by the model's tests that run without the hold, not by a node.
- With the hold on, which after {{pr-09}} is always, the re-queue reason `stale_resend` can no longer be counted: a header enters the tracked set only behind a guard that returns early for a round at or below the last committed own round, and that round only rises in the call that removes every tracked header at or below it.
  After a restart, a re-proposed header that had already committed counts as `unknown_seq`.
  The reason and its metric label stay, and the label stays at 0; see {{pr-09}}.

Nothing that should have been fixed before the merge is open.

## Related

- Refs #1807: once {{pr-09}} lands the hold is the node's behaviour; the closing keyword for #1807, if any, is in #1862's body, the only PR of the stack that merges into `main`.
- Refs #1794: a held digest keeps its slot in that bound until it commits.
- Merged into #1868's branch on 2026-11-16; {{pr-09}}, which removes the stack's switches, targets #1862's branch and is the last PR of the stack.
