# Review scope — parent-grace

Topic footer(s): `Topic: parent-grace`. Upstream issue: #1803. Switch: `parent_grace` (duration; default `0s` = off; the benchmark uses `150ms` and `100ms`).
Branch head when this was written: dc7855cc6. Size: 2 commits, +1038 lines (tests included).

## Commits (the diff under review, in branch order)
- `5c1c28720` feat(config): add the parent_grace switch
- `80584c6f6` feat(primary): wait a bounded parent grace for last round's authors

## Files touched
- `crates/config/src/node.rs`
- `crates/consensus/primary/src/metrics.rs`
- `crates/consensus/primary/src/proposer.rs`
- `crates/consensus/primary/src/tests/proposer_tests.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table row `parent_grace` and the row `parent-grace` under "Node log lines and metrics" (what is logged and counted, the cap, when no grace is armed).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, section "From U9 (parent grace…)" (as built; decisions D37, D38; what `missing` can include).
- The upstream issue body: find it with `ls /home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/ | grep -i -e grace -e parent -e far` (the far-validator certification problem the grace is for).
- The unit's checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u9.md`.

## Questions specific to this topic (2g)
1. The grace is "bounded": verify every bound in code — the cap at `max_header_delay`, no grace in the first two rounds of an epoch, what ends a grace early (`complete`, `preempted`) — and look for any path on which the proposer could wait past the cap or re-arm a grace for the same round.
2. Does waiting change WHICH parents a header carries in a way another validator could reject, or that changes leader election or commit rules? A header with more parents is still a valid header: confirm from the validation code.
3. Interaction inside the proposer with the other bench-6 topics that touch the same file (`quorum_exec_block`, `digest_dedupe`, the digest-wait accounting): can an armed grace hold digests or an execution reference longer than those topics assume?
4. D38 says one slow author can cost every other round at most G: is that bound right, and can two authors make it every round as stated? Is there a cheap way to cap repeated graces for the same author?
5. The proposer's own certificate can be among the `missing`: can a node whose own headers fail to certify end up delaying itself every round?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/parent-grace-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-parent-grace.md`
