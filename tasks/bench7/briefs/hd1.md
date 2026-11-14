# HD-1 — #1807 observability in the proposer (no switch)

Unit: `HD-1` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-1.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-hd1`, branch `b7/hd1`, base = the integration head with PT-0 and PT-3a in it (the orchestrator creates it; `proposer.rs` there already carries PT-0's first-receipt change and the vote fix: you are the file's next writer). Domains: `tn-domain-consensus`, `tn-domain-worker`. Plan rows: "#1807: the own-chain hold → HD-1".
Topic slug: `digest-order-hold`. Stack head: `fix/1807-digest-order-hold` (PR 06, opened only after bench 7). `Refs #1807`.

## Why

Issue #1807: an accepted transaction lands late or never without a resend. Bench 6 traced it to one mechanism (`benchmark/private/bench7-prep/design/issue-1807-findings-from-bench-6.md`): an own header that does not commit has its batch digests re-queued to the FRONT of the worker's queue after a newer own header already drained newer digests of the same worker; the older batch then executes after the newer one, and its transactions fail on their nonces (or sit behind a gap) until the sender resends.
The fix (unit HD-2, after you) is a hold in the proposer. Before it, and independent of it, the node must be able to SAY when this happens: today nothing counts an out-of-order re-queue.
Design: `benchmark/private/bench7-prep/design/design-1807-own-chain-hold.md` §5 (unit "U1": observability) and §6 (what the fleet reads). **The delta read on M is binding where it differs**: `benchmark/private/bench7-prep/DR-1807/findings.md` (verdicts 1, 2, 6 and "Changes to the design" items 1 to 4 and 12). The design's line numbers are from another tree: use DR-1807's anchors, then `grep -n`, because PT-0 and PT-3a moved lines again.

## What to build — observability only; header contents byte-identical to your base

1. **A per-(author, worker) sequence on queued digests.** Add `seq: u64` to `ProposerDigest`, set at the push from the worker (DR-1807: `proposer.rs` ≈ :1230) from a per-worker counter that only grows within the proposer's life (one epoch). The sequence must survive a re-queue: `push_payload` rebuilds re-queued digests from the bare `Header`, so keep the drained `ProposerDigest`s (or a `digest → (worker, seq)` map) beside `proposed_headers`, and drop an entry when its header is forgotten. A digest whose sequence is not known (a header re-sent after a restart) counts as `unknown`, never as out of order.
2. **`tn_primary.requeued_out_of_order_total{cause}`** (labelled counter through a handles struct like M's `DigestsRequeuedHandles`, reusing `RequeueCause` = `committed` | `canceled`; add the label value `unknown_seq` only if you count those separately, and say so): incremented once per re-queued digest whose `seq` is LOWER than the highest `seq` of the same worker already drained into any header since (i.e. a newer digest of the same lane has already left the queue). Define "already drained" precisely in the doc comment; the definition is the KPI.
3. **Fields on the `header proposed` line** (written inside the spawned `propose_header`, so pass them through `ProposalTrigger`): `own_parent` (bool: the parents this header carries include this node's own certificate of the previous round), `held` (count of digests left in the queue by the hold: always 0 in this unit, HD-2 fills it), `held_lanes` (count of workers held: 0 here), `blockers` (count of tracked older own headers not proven ancestors: compute it now if it is cheap and exact without the hold's bookkeeping; otherwise 0 here and say so). Keep every existing field and its order; new fields go at the end.
4. **A `proposer stopped` info line** in the shutdown arm (DR-1807: ≈ :1212-1214, which logs nothing today): fields `epoch`, `round`, `queued_digests` (left in the queues), `proposed_uncommitted` (own headers proposed and neither committed nor canceled), `uncommitted_digests` (their digests). This is what says, at an epoch's end, how much the orphan re-pool is about to receive.
5. **The dropped cancel report**: DR-1807 found three ways a `report_canceled` is dropped (`certifier.rs` ≈ :781-801): the shutdown guard (no log), a full channel (a debug line), no subscriber (silent `Ok`). You do not own `certifier.rs`. If a counter for the drop can be added from the proposer's side without it, do it; otherwise list it as a cross-unit need (unit HD-4 owns `certifier.rs` for its test hook).

## Files you own

`crates/consensus/primary/src/proposer.rs`, `crates/consensus/primary/src/metrics.rs`, `crates/consensus/primary/src/tests/proposer_tests.rs` (new tests at the END under `// ---- bench7 digest-order-hold ----`).
Not yours: `certifier.rs`, `consensus_bus.rs` (nobody's), `crates/config/src/node.rs` (no switch here).

## Tests

- The sequence grows per worker, is kept across a `committed` re-queue and a `canceled` re-queue, and is `unknown` for a restart re-propose.
- The counter: a scripted proposer (the existing re-queue tests at ≈ :1611, :1666, :1706 show how) where header N with worker-0 digests is canceled after header N+1 drained newer worker-0 digests → the counter rises by the number of N's worker-0 digests with `cause="canceled"`; the same through the commit path → `cause="committed"`; a re-queue with nothing newer drained → 0; two workers, only one overtaken → only that lane counts.
- The `header proposed` fields and the `proposer stopped` line (capture logs as the crate's tests do).
- **Byte-identity**: for a fixed scripted sequence, the headers proposed (digest, payload order) equal those of your base commit; record how you checked it (a golden list in the test, or the base's own tests passing unchanged).
- Whole-package nextest for the primary; each new test three times by name.

## Gates and review

As the rules say; then one `tn-domain-reviewer` (opus) on your diff, domains consensus and worker: ask whether the bookkeeping can grow without bound within an epoch and whether any new state is read on the path that decides a header's contents (it must not be).

## Hand back

As the rules say, plus: the exact definition of "out of order" as coded; every new field, line and metric verbatim; the API HD-2 builds on (the `ProposerDigest` shape, where drained digests are kept, how a header is forgotten) in under 30 lines, also written to `tasks/bench7/briefs/hd1-api.md` (you own that one file in devnet-genesis).
