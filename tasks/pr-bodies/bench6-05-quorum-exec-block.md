## Summary

Adds the author's side of #1804 behind two runtime switches, `quorum_exec_block` (default `false`) and `quorum_exec_block_starved_rounds` (default `0`); in this PR's diff, at the defaults, every header names the proposer's own newest executed block, as on main.
With `quorum_exec_block: true` a header names the highest execution block that holders of 2f+1 voting weight, among the proposer's own tip and its same-epoch parents, have reached: capped at the own tip, never older than 8 entries back in the recent-blocks ring (the floor), never older than the block the epoch opened on.
With the count left at `0` every header uses the rule: this always-on form is the one the repository owner chose, after bench 6 and bench 7, as the only form that ships.
A count K above zero selects the adaptive form, kept for comparison: the own tip, and the rule only for the next K headers built after an own header was cancelled uncertified, K doubling up to 128 while cancels go on and returning to the configured value after 64 certified tip headers in a row.
Every node, switch on or off, logs four new fields on `header proposed`.

{{pr-09}}, the last PR of the stack, removes both switches and makes the always-on form the node's behaviour; once the stack is collapsed into #1862 there is no switch.
{{pr-09}} also deletes the adaptive form: its window, its reset streak, its two constants (the 128-header cap and the 64-header streak) and their tests.
The adaptive form is deleted because the repository owner chose always-on as the only form that ships, and because of bench 7: it ran one run of each form at 20,000 IOPS, and in that pair the adaptive form did not do better (in the table below three rows are not told apart, and on the two rows outside the always-on run's spread the adaptive run is behind); bench 7 made no run at 50,000 IOPS, where bench 6 had the adaptive form ahead on certification.
The adaptive form also carries code the always-on form does not need: a window, a streak and two constants.

PR 7 of 9 in the stack #1862 to {{pr-09}}; #1862 targets `main`, this PR targets #1867's branch (`fix/epoch-loop-output-drop`), so the Files tab shows this change alone (18 commits).
The stack will be collapsed into #1862 (each PR merged into the branch below it); `main` is then merged into that branch and `make attest` runs on the result.
Please merge with 'Create a merge commit': a squash would leave the pull requests above this one with commits their base no longer has.

## Problem

On main at 33b727fce the proposer passes `consensus_bus.app().latest_execution_block_num_hash()` into `Header::new` (`crates/consensus/primary/src/proposer.rs:379-385`), so every header names the author's own newest executed block.
A voter waits up to 1 s for that block (`crates/consensus/primary/src/network/handler.rs:1462-1507`) and refuses as execution-behind if it has not executed it, so a validator that executes ahead of a quorum of voters loses their votes.
Bench 5 ([r20261107-1504](https://benchmark.telcoin.network/runs/r20261107-1504/)) showed this on its fastest executors (#1804).
The e2e test `test_fast_executor_is_certified` reproduces it on four nodes, three of them executing late: with every switch off the fast node must certify at most 0.85 of its own headers, or the test fails.

Bench 6 ran an earlier form of these switches on an older base: the always-on form in [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) and [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/), the adaptive form in [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) and [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/).
At 20,000 IOPS, in the load blast's mixed phase before validator-05 is killed, fleet certification of own headers was 99.94 % in r20261113-1351 and 99.56 % in r20261113-2118; at 50,000 IOPS the adaptive form was ahead on certification and behind on the senders' cost.

Bench 7 ran this head's node logic, on an earlier cut of the stack on main at 45dce8947 (branch `bench/bench7-2026-11`), once per form at 20,000 IOPS with ten validators: the always-on form in [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/), the adaptive form in [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/).
With one run per form, a difference counts only outside the always-on run's own spread, the range over its 300 s buckets of the same window (60 s blocks for the first light blast); no row carries a significance test.

| Row (window, unit) | r20261115-1131, always-on | r20261115-1653, adaptive | Always-on run's spread | Verdict |
|---|---|---|---|---|
| Load blast, headline window, chain tx/s | 9,289 | 9,337 | 8,344.6-10,544.9 | not told apart |
| Load blast, own-header certification, fleet (%) | 95.59 | 95.00 | 93.37-97.29 | not told apart |
| Load blast, committed rounds per second (chain) | 2.32 | 2.22 | 1.99-2.73 | not told apart |
| Load blast, seen p95 (s) | 17.33 | 24.18 | 14.27-18.78 | outside |
| First light blast, all-generators window, chain tx/s | 698.3 | 680.0 | 688.2-722.8 | outside |

Per-validator certification moved both ways: of the 41 per-bucket rows outside the validator's own range in the always-on run, 28 are lower in the adaptive run and 13 higher.
Before the kill (817 s and 1,121 s long) validator-01 went from 100.0 % to 89.2 % and validator-08 from 86.4 % to 99.2 %; the pair does not separate the form from which validators lagged.
Under load the adaptive form mostly ran its window: 61.5 % of r20261115-1653's headers over the load blast were built inside it, measured from the logged `exec_policy`.
Replayed from the logs (the replay matches the logged policy on 99.875 % of headers), 56.3 % of its windows before the kill and 89.1 % after validator-05's start opened at the 128-header cap.
A return to the own tip lost 1.66 own-tip headers on average, and 64.0 % of returns lost their first header.
What the window bought is a fresher named block: the fleet mean distance from the tip to the named block fell from 7.57 to 4.83 block-bearing outputs; what that is worth was not measured.

## Change

- `7f81ab652` feat(config): add the quorum_exec_block switches: the two fields, defaults `false` and `0`, listed in `runtime_switches!`.
- `dd5f48f2d` feat(primary): resolve recent blocks by number and by entries back from the tip: two lookups on the recent-blocks ring, unused with the switch off.
- `829aa322f` feat(primary): name an execution block a quorum holds behind quorum_exec_block: the rule (`choose_exec_block`), the adaptive window and the four log fields; the number and hash named are always this node's own ring entry, never a parent's.
- `5de0491a1` fix(primary): reset the adaptive exec-block window only after a streak of certified tip headers: 64 in a row; any cancel report restarts the count.
- `eba4faa3d` fix(primary): never name an execution block from before the epoch opened: a parent naming a block older than the previous epoch's closing block is not counted, so a voter restored from that epoch's export cannot refuse the header for good.
- `2720304e9` fix(primary): warn on quorum_exec_block_starved_rounds values the proposer cannot use: a count above 128 is lowered to 128, a count with the first switch off has no effect, and either is warned once per epoch.
- `44247215a` docs(primary): say when the quorum rule skips a parent and what the opening-block bound assumes.
- `84af6653c` test(primary): pin the quorum rule's inputs to the committee's epoch above epoch 0.
- `94d0c84d6` fix(primary): count the adaptive exec-block window in headers built: a lagging validator skips rounds, so a window of rounds could pass with no header built under the rule and still double the next one.
- `f3b00f18d` fix(primary): bound the quorum exec-block choice at the epoch's opening block: a final bound names the opening block (`exec_basis=floor`) if a choice fell below it; on an honest node it never fires, and a debug assertion says so.
- `8b673c528` test(primary): pin what faulty high parents cost the quorum exec-block rule.
- `aae70e162` docs(primary): say what the exec-block floor does not bound, and the upstream refusal.
- `541dcaf07` test(primary): make the proposer's round-jump check tell windows of headers from rounds.
- `803b8abf0` docs(primary): say what the opening-block bound covers and what moves the run start.
- `1f8f9c076` test(primary): pin the voter's answers to an old execution block: on main's reworked vote handler, with `vote_queue_fix` off and on; no voter code changes.
- `f83f420f7` docs(primary): say the adaptive exec-block window counts headers.
- `618905035` test(e2e): fast executor certification and a mixed-switch fleet.
- `38f00e88e` test(e2e): two epoch closes under each vote-fix form with members held behind.

{{pr-09}} removes what these commits add for the adaptive form (the window, its reset streak, its cap and the warnings about `quorum_exec_block_starved_rounds`) and keeps the rule with its floor of 8.

## The switches, and where they go

In this PR's diff, with the switch off, every header names the block from the call main makes, `consensus_bus.app().latest_execution_block_num_hash()` (`proposer.rs:1908`).
New with it off, in this diff: two reads of the switches when each epoch's proposer is built, with a warning only for a count above zero (`proposer.rs:305-318`); per header, policy bookkeeping that returns at once; the fields `exec_block`, `exec_tip`, `exec_basis` and `exec_policy` (`off`) on `header proposed` (`proposer.rs:478-481`); and the two switches on the `node switches` line.
`parameters.yaml` is unchanged at the defaults.

{{pr-09}}, the last PR of the stack, removes both switches and the adaptive form, so once the stack is collapsed into #1862 there is no switch and no off state.
A reviewer should read the rule as unconditional: after {{pr-09}} every header of every node names the block `choose_exec_block` picks under the quorum rule with the floor of 8.

In this PR's diff a mixed fleet is one chain: the switch changes only a header's `latest_execution_block` (and so its digest), votes, certificates and batches are unchanged, and the voter never reads the switch.
Every choice is the proposer's own executed ring entry, at or below its tip and, once the proposer has executed the block the epoch opened on, at or above that block (before then it names its own tip, as the switch-off form does); a voter with the switch off answers it as it would answer an older tip.
`test_mixed_switch_fleet_is_one_chain` runs a fleet with the switches mixed; {{pr-09}} deletes it with the switches.
After {{pr-09}} the mixed fleet that matters is main beside the stack during a rolling upgrade: `make test-upgrade` with main as the previous binary passed on the stack's top with the six switches on (see the gates below), and the limits say what that test does not cover.

## Testing

Unit tests in `crates/consensus/primary/src/tests/proposer_tests.rs`, among 15: `test_quorum_exec_block_choice_table`, `test_quorum_exec_block_self_feeding_fleet`, `test_quorum_exec_block_switch_off_keeps_header_bytes`, `test_quorum_exec_block_window_counts_headers_across_a_round_jump`, `test_quorum_exec_block_reset_needs_a_streak_of_certified_tip_headers`, `test_quorum_exec_block_policy_model_holds_the_target`, `test_quorum_exec_block_never_names_a_block_before_the_epoch_opened`, `test_quorum_exec_block_faulty_high_parents_cost_the_gain_only`.
In `crates/consensus/primary/src/tests/network_tests.rs`, the 14 `quorum_exec_block_voter_*` tests pin the voter's answers to an old block, seven cases each with `vote_queue_fix` off and on: an executed block is voted at once from the ring or, once it left the ring, from the database; previous-epoch blocks are answered; an old number with another hash is refused; a block above the voter's tip is waited for.
E2e, in `crates/e2e-tests/tests/it/exec_block.rs`: `test_fast_executor_is_certified` (switches off, the fast node certifies at most 0.85 of its headers; the adaptive form with `vote_queue_fix`, at least 0.88 and more than with them off; the always-on form with `vote_queue_fix`, every node at least 0.93) and `test_mixed_switch_fleet_is_one_chain`; in `epoch_close_forms.rs`, `test_held_member_two_closes_always`, `test_held_member_two_closes_adaptive`, `test_missed_record_round_always` and `test_missed_record_round_adaptive`.
{{pr-09}} deletes the adaptive form's tests (its eight unit tests, among them the window, streak and model tests above, `test_held_member_two_closes_adaptive` and `test_missed_record_round_adaptive`), `test_quorum_exec_block_switch_off_keeps_header_bytes` (`test_quorum_exec_block_header_names_the_own_ring_block` checks the header's block and its three fields instead), the control and adaptive arms of `test_fast_executor_is_certified`, `test_mixed_switch_fleet_is_one_chain` and, with `vote_queue_fix`, the seven voter tests that turn that switch off; the always-on tests and the other seven voter tests stay, some under new names.

On main at 33b727fce, at this head's tip `38f00e88e`:
- Every one of the 86 commits from main to the tip, this topic's 18 among them, compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied).

This topic's 18 commits applied on an earlier tip of `fix/epoch-loop-output-drop` (15f60ff82); that tree differs from this head's only in `crates/state-sync/src/epoch.rs` and `crates/state-sync/src/metrics.rs`:
- `cargo nextest run` over `tn-config`, `tn-types`, `tn-primary`, `tn-node` and `state-sync`: 1,392 passed, 7 skipped.
- `cargo +nightly-2026-03-20 clippy` over `tn-config`, `tn-primary`, `tn-node` and `e2e-tests`: no warnings; `cargo fmt` clean.

Not run on this head: the bench 7 runs above ran its node logic on main at 45dce8947; no bench 7 run was made at 50,000 IOPS.

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

- Certification fell against bench 6 while throughput rose. Over the load blast's headline window (all generators, the kill inside), chain tx/s went from 5,322 (r20261113-1351) to 9,289 (r20261115-1131) and from 5,395 (r20261113-2118) to 9,337 (r20261115-1653); in the mixed phase before the kill, fleet certification went from 99.94 % to 94.0 % and from 99.56 % to 94.95 %.
  The storage engine, main's vote-handler rework, the order hold, the voters' execution lag and the run's shape changed together, and for the adaptive pair the window's rule too (it now counts headers built, not rounds); no counter separates them.
- Under-held headers: over the whole load blast, 10.31 % of r20261115-1131's headers and 12.55 % of r20261115-1653's named a block that at most five other voters held at the proposal; they certified 61.25 % and 66.70 % of the time, the rest 99.53 % and 99.06 %.
  Arithmetic on these two runs, holding the rest fixed, says a floor of 16 entries leaves none under-held, at the cost of an older named block (14.71 and 13.81 block-bearing outputs from the tip, against the measured 7.57 and 4.83: about twice as far in r20261115-1131 and almost three times in r20261115-1653); that is arithmetic, not a result, and the floor stays at 8.
- The floor counts ring entries, not rounds or time: under light traffic the named block can be old, and an honest node notices its own execution fork up to eight block-producing outputs later than when it names its own tip, as main does (`proposer.rs:1530-1545`).
- No bench 7 run at 50,000 IOPS, where bench 6 found the two forms differed.
- The adaptive form adds code the always-on form does not need: the window, its 128-header cap, the 64-header reset streak and the return to the tip.
  After {{pr-09}} always-on is the only form, on every node, and that code is gone.
- {{pr-09}} deletes the control arm of `test_fast_executor_is_certified`, which showed that without the rule the fast node certifies at most 0.85 of its headers and every slow voter refuses some requests as execution behind; after it the test asserts absolute bounds under the rule, with no run without it to compare against.
- {{pr-09}} deletes `test_mixed_switch_fleet_is_one_chain`: one chain while two nodes ran the fixes and two did not, across epochs and a restart, every node serving the same certified record per closed epoch, no record conflict, and a certified header of a fixed node naming an older block, which needs a vote from a node without the fixes.
  `make test-upgrade` as it ran in the gates below, with main as the previous binary, covers old and new binaries making one chain through a rolling upgrade, but not that last point: it slows no node and reads no `exec_basis`, all four validators execute at the same speed, so an upgraded proposer names its own tip almost always, and nothing asserts that a voter running main ever voted for a header naming an older block.
  The voter-side unit tests that stay exercise this tree's voter, not main's.
  Whether a test of that point is added to the rolling-upgrade test: see {{pr-09}}.
- {{pr-09}} removes the field `exec_policy` (values `off`, `always`, `tip`, `starved`) from `header proposed`; `exec_block`, `exec_tip` and `exec_basis` stay.
- f faulty parents that name high blocks and withhold their votes can cancel a header under the rule; the loss is bounded by the rule's gain (`test_quorum_exec_block_faulty_high_parents_cost_the_gain_only`).
- The rule relies on the voter answering an executed old block at once; the `quorum_exec_block_voter_*` tests pin that, and a recency check added to the voter would work against this rule.
- The opening-block bound matches a restored voter's floor only because state exports are taken at an epoch's closing block (`proposer.rs:1949-1957`).

Nothing that should be fixed before merge is open.

## Related

- Refs #1804: the author's side; the voter's side is `fix/1804-vote-queue` (#1864); the closing keyword for #1804, if any, is in #1862's body, the only PR of the stack that merges into `main`.
- Next: `fix/1807-digest-order-hold` (#1869), the order hold for #1807, builds on this head; {{pr-09}}, which removes the stack's switches, is the PR on top of #1869.
