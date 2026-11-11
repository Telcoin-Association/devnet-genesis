# Review scope — vote-starvation

Upstream issue: #1804. Switch: `quorum_exec_block` (bool), `quorum_exec_block_starved_rounds` (count; 0 = the rule on every header, 4 in the benchmark = own tip by default and the quorum rule for 4 rounds after an own header was cancelled uncertified, doubling up to 128), `vote_queue_fix` (bool).
Where: the checked-out branch `bench/bench6-2026-11`, head 56f66e160. Size: 10 commits, +3582 lines (tests included).

## Commits (the diff under review, in branch order)
- `86755c450` feat(config): add the quorum_exec_block switches
- `82ed5801a` feat(config): add the vote_queue_fix switch
- `d4be3a435` feat(primary): resolve recent blocks by number and by entries back from the tip
- `5d7821dfb` feat(primary): name an execution block a quorum holds behind quorum_exec_block
- `2b9a69925` fix(primary): wait for execution before the per-author vote lock
- `14b55b04c` test(primary): pin the voter's answers to an old execution block
- `8bd68e514` test(e2e): fast executor certification and a mixed-switch fleet
- `31ef1149c` test(e2e): require only a gain over the control from the adaptive arm
- `20858d28d` fix(primary): reset the adaptive exec-block window only after a streak of certified tip headers
- `56f66e160` test(e2e): require 0.88 from the adaptive exec-block arm

## Files touched
- `crates/config/src/node.rs`
- `crates/consensus/primary/src/error/network.rs`
- `crates/consensus/primary/src/metrics.rs`
- `crates/consensus/primary/src/network/handler.rs`
- `crates/consensus/primary/src/network/message.rs`
- `crates/consensus/primary/src/proposer.rs`
- `crates/consensus/primary/src/recent_blocks.rs`
- `crates/consensus/primary/src/tests/network_tests.rs`
- `crates/consensus/primary/src/tests/proposer_tests.rs`
- `crates/e2e-tests/tests/it/exec_block.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the three switch table rows and the rows `quorum-exec-block` and `voter-lock` / `vote-queue` under "Node log lines and metrics" (`header proposed` fields `exec_block`, `exec_tip`, `exec_basis`, `exec_policy`; `vote path timing`).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From I-4", "From U1" and "From U2" (design D and why it has two policies: applied to every header it settles 8 outputs behind the tip; D1, D2, D29, D30, D34).
- The issue body `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/bench5-execution-behind-vote-starvation.md`, the design `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-4/unit-specs.md` (§U1, §U2) and the unit checkpoints `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u1.md`, `…-u2.md`.
- The e2e result for these fixes, if it exists when you start: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-st-a.md`.

## Questions specific to this topic (2g)
1. The header's execution reference (`exec_block`) is what other validators check before they vote. With the rule on, the proposer names an OLDER executed block than its own tip. Read the vote handler: is a header that names a block the voter has executed, but that is older than the voter expects, always acceptable? Is there a lower bound a voter enforces that the floor rule could fall below (stale reference, epoch boundary, a block before the epoch's first)?
2. Safety of the reference: can the rule ever make a proposer name a block it has NOT executed, or a block on a different fork than a quorum holds? What does the code use as evidence of what a quorum has executed, and can a Byzantine minority skew it (downward: stall freshness; upward: make honest headers unvotable)?
3. The adaptive policy keeps per-node state (starved rounds K, doubling to 128, reset rule D29). Find a sequence in which K never resets, or resets every round, and say what the fleet then looks like. Does the state survive an epoch change or a restart, and should it?
4. `vote_queue_fix` changes how the voter orders or bounds waiting votes (the `prelock_wait_ms` path). Can a vote for a valid header now be dropped or answered late enough to be useless where before it would have been cast? Can one peer's headers starve another's under the new order?
5. Mixed fleet is the central risk for this topic: proposers with the rule on, voters with it off, and the reverse. Walk both directions.

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/vote-starvation-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-vote-starvation.md`
