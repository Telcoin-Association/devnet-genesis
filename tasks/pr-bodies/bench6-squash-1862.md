Vote stalls, digest order, epoch records: fixes and node metrics (#1862)

The stack #1862 to #1869 and {{pr-09}}, collapsed into one change.

#1862 (`feat/bench6-switches-obs`): a gauge of how far behind a node enters an epoch (`tn_primary_epoch_entry_rounds_behind`), and sub-millisecond buckets on ten execution-stage histograms.
A digest keeps its first receipt across a re-queue, so `tn_primary_digest_wait_seconds` measures from it; `header proposed` gains `oldest_requeue_wait_ms`.

#1863 (`test/bench6-e2e-scaffold`): an e2e test can give chosen nodes their own `parameters.yaml` entries and environment (`NodeOverrides`, `FleetOverrides`), and a test lane can set fleet-wide entries through `TN_E2E_PARAMETERS`.
Test code only; the node log helpers of `restarts.rs` move to `common.rs`.

#1864 (`fix/1804-vote-queue`): a voter waits for the execution block a header names, up to 1 s, before the per-author vote lock instead of under it, and refuses at once a request older than that author's newest (`SupersededRequest`, recoverable, no penalty).
A node needs `vote_timeout` below 9 s to start, and every node counts vote requests by outcome.

#1865 (`fix/epoch-record-closing-block-check`): before a node saves, votes on or publishes an epoch record, it checks that the record's `final_state` is the block where the epoch-closing calls ran.
A failing block stops the node.

#1866 (`fix/epoch-record-collector-hardening`): the record collector walks past an epoch this node holds only as its own uncertified record, and vote rounds keep verified signatures across rounds and re-vote one older uncertified record of the node's own.
Also the serving peer on `retrieved cert` lines, the gauge `tn_state_sync.epoch_records_certified_through`, an info line for a false quorum error, and a vote queue that never evicts the rounds of the newest record or the one before it.

#1867 (`fix/epoch-loop-output-drop`): the epoch loop reserves room in the engine channel before it takes a consensus output, so an exit that pre-empts the forward no longer drops the output.
The leftover drain skips an output already forwarded and stops the node on a gap, before the engine executes past it.

#1868 (`fix/1804-quorum-exec-block`): a header names the highest execution block that holders of 2f+1 voting weight, among the proposer's own tip and its same-epoch parents, have reached, capped at the own tip and never older than 8 entries back in the recent-blocks ring.
`header proposed` logs `exec_block`, `exec_tip` and `exec_basis`, and the epoch-close e2e tests check every record against its closing block on chain.

#1869 (`fix/1807-digest-order-hold`): a validator's next own header leaves queued every digest of a worker named in an older own header that the new header's parents do not prove to be on its own chain, until that older header commits, is canceled or re-queued, or the epoch ends.
Header validity, the messages and what peers vote for do not change; every node counts digests re-queued out of order.

{{pr-09}} (`refactor/remove-bench-switches`) removed again the six runtime switches the stack had added (`vote_queue_fix`, `epoch_record_collect_past_uncertified`, `epoch_record_recertify`, `quorum_exec_block`, `quorum_exec_block_starved_rounds`, `digest_order_hold`), the switch list, the `node switches` log line and the `tn_node_switch` gauge.
Each change that sat behind a switch is the node's behaviour; of the two forms of #1868's rule only always-on is kept, and `Parameters` has main's fields and defaults again.

Fixes #1851: the closing-block check (#1865); its e2e verification, the markers checked on chain, is in the epoch-close tests #1868 adds.
Fixes #1852: every point of its sketch, including its open question: the gauge reports the held certificate's signers (#1866).
Fixes #1860: both parts of its proposed fix, and its reproducing test passes (#1867).
Refs #1804: both sides are the node's behaviour after {{pr-09}}, the voter's (#1864) and the author's in its always-on form (#1868); left open: the depth of the floor of 8, which the executors' spread outgrew at 50,000 IOPS in bench 6, and the wait for a pending parent that #1842 put under the vote lock, which #1864 does not move.
Refs #1807: the own-chain order hold (#1869) is the node's behaviour after {{pr-09}}; left open: the issue's second defect, a resend that executes beside the original because a sealed transaction is invisible to the pool and the RPC, which the hold does not touch, and why some re-queued batches never executed.
Refs #1850: the walk past an uncertified epoch and the re-certify round (#1866) are the node's behaviour after {{pr-09}}, and its conflicting-record case was fixed on main by #1849; left open: the question in its comment, whether that stop should need a super-quorum of the full committee; a node without its own record of the epoch still needs re-certification, and no fleet run of either change is reported (#1866).
Refs #1806: the epoch-entry gauge measures how late a member enters an epoch (#1862).
Refs #1819: its digest-wait histogram now counts across re-queues (#1862).
Refs #1782: the bounded execution wait, which #1864 moves in front of the author's vote lock.
Refs #1794: a held digest keeps its slot in #1794's bound until it commits (#1869).
