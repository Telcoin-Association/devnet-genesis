# HD-2 — the own-chain hold in the proposer (`digest_order_hold`, issue #1807)

Unit: `HD-2` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-2.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-hd2`, branch `b7/hd2`, base = the integration head with PT-0, PT-3a and HD-1 in it (the orchestrator creates it). Domains: `tn-domain-consensus`, `tn-domain-worker`. Plan rows: "#1807: the own-chain hold → HD-2", decision 4.
Topic slug: `digest-order-hold`. `Refs #1807`.
Read first, besides the rules: `tasks/bench7/briefs/pt0-api.md` (how to add a switch), `tasks/bench7/briefs/hd1-api.md` (what HD-1 left you: the per-lane sequence, where drained digests are kept, the fields waiting to be filled).

## The rule (design `benchmark/private/bench7-prep/design/design-1807-own-chain-hold.md` §3; read §1 to §4 and §7 in full)

At the build of header N at round n with parents P:
- `own` = the parent whose origin is this node and whose header digest equals the tracked own header at round n−1.
- `blockers(N)` = `unproven(n−1) ∩ tracked` if `own` is present; otherwise every tracked older own header that carries digests.
- N drains no digest of any worker named in a blocker's payload (those digests stay queued, in order).
- Record `unproven(n) = blockers(N)`, also for an empty header.
- A restart re-proposal records the tracked older headers; a max-delay re-send keeps its existing record.
Header contents only: no timing change, no wire change, no validity change; with the switch off the drain is the base's, byte for byte.

**The delta read on M is binding where it differs** (`benchmark/private/bench7-prep/DR-1807/findings.md`, "Changes to the design" items 1 and 5 to 9, and verdict 3's wording correction): M's anchors; `handle_proposal_result` cannot tell a new header from a restart re-propose or a max-delay re-send (carry the kind with the pending task, or treat an insert at a round already holding the same digest as a re-send); take the parents BEFORE the drain (swap the two lines; same synchronous arm, no race); the switch registers on PT-0's machinery; the dropped-report test covers all three drops; no `digest_dedupe` test; the module doc states that an older own header that is not an ancestor of the next own header is ordered before the newer one or never, so overtaking comes only from the committed-kind re-queue.
New on M and relevant to the hold's cost: peers hold at most 500 of this node's uncommitted batches (#1794, `handler.rs` ≈ :85) and age them out after 50 committed rounds. The hold keeps digests QUEUED (not proposed), which is not the same as uncommitted-at-peers: establish from the code whether a held digest counts against that quota (it was already reported to peers by the worker at seal time?) and state it in the hand-back; do not change the quota.

## What to build

1. `crates/config/src/node.rs`: `digest_order_hold: bool`, default false, doc (what it changes, the issue, the cost), through PT-0's machinery; your field only.
2. New `crates/consensus/primary/src/order_hold.rs`: a pure `OwnChainOrder` (`BTreeMap`/`BTreeSet` only, no hashing order anywhere) with `plan(round, &parents, &proposed_headers, &author) -> HoldPlan { held_workers, blockers, own_parent }`, `record(round, …)`, `forget(round)`; unit-tested on its own; `pub(crate)`; module doc = the rule, the invariants I1 to I3, the safety argument with DR-1807's correction, the GC-cut residual (an own-chain ancestor more than the GC depth below the leader can still be overtaken: counted, not prevented).
3. `proposer.rs`: `propose_next_header` takes the plan from the parents the header will carry, then drains through `drain_digests_for_header(&held)`; `handle_proposal_result` records for a NEW header only; both re-queue paths `forget`; HD-1's `held`, `held_lanes`, `blockers` fields get their real values. The bookkeeping is bounded (forgotten with the header; cleared with the epoch's proposer).
4. `metrics.rs`: `tn_primary.headers_held_total` (headers that left at least one digest queued because of the hold), `tn_primary.digests_held` (gauge: digests currently queued behind a hold; back to 0 when no blocker is left). With the switch off both stay 0.
5. Invariant I2 in production: a re-queued digest older (by lane sequence) than a digest of the same lane sitting in a tracked or committed header → HD-1's `requeued_out_of_order_total` already counts it; with the switch ON add one `warn!` per header (not per digest) because it would mean the hold failed; in tests it is an assertion.

## Files you own

`crates/config/src/node.rs` (your field only), `crates/consensus/primary/src/order_hold.rs` (new) and its `mod` line, `crates/consensus/primary/src/proposer.rs`, `crates/consensus/primary/src/metrics.rs`, `crates/consensus/primary/src/tests/proposer_tests.rs` (new tests at the END under the `// ---- bench7 digest-order-hold ----` marker HD-1 opened).
Not yours: `certifier.rs`, `types/src/test_hooks.rs` (the e2e unit HD-4), `close_epoch.rs` (HD-3), any property-test file (unit HD-2p writes the model test against your `OwnChainOrder` after you hand back: keep `plan`/`record`/`forget` pure and callable without a proposer).

## Tests (unit; the design's §4 list, on M)

- Canceled: round r carries no worker-w digest; r+1 carries d1, d2, d3 in order. Switch off: pin the base's payload and `out_of_order = 2`. Switch on: r+1 holds lane w, the canceled header's digests come back at the front, the next header carries them in order, `out_of_order = 0`.
- The race (r−1 certified but missing from the parents) and the committed notice arriving later.
- A steady own chain: nothing is ever held (the cost is zero while the chain is intact).
- Transitive `unproven` through several rounds; reverse report order; a round jump.
- A dropped cancel report in each of its three forms: the lane stays held until the commit notice or the epoch's end; nothing executes out of order; `proposer stopped` reports what is left.
- Restart re-propose and max-delay re-send keep or build the right record.
- Two workers: only the lane named in a blocker is held; the other lane drains normally.
- **Switch-off golden**: same header payloads as the base for a fixed script (I3).
- Whole-package nextest for the primary and the config crate; each new test three times by name.

## Gates and review

As the rules say; then one `tn-domain-reviewer` (opus) on your diff, domains consensus and worker, asked specifically: can the hold starve a lane forever (liveness: what releases every blocker, in the worst case the epoch's end), can two honest nodes disagree on anything because of it (they cannot: it only changes what this node proposes; confirm), is any decision driven by wall-clock or hash-map order.
If a test shows the rule is wrong or incomplete on M (not a coding slip: a hole in the rule), STOP: the plan says a design change goes back to the user. Hand back with the failing scenario written out.

## Hand back

As the rules say, plus: the rule as coded in ten lines; what releases a held lane in each case; whether a held digest counts against #1794's quota; every new metric and field verbatim; the pure API for the property test (signatures) in under 25 lines, also written to `tasks/bench7/briefs/hd2-api.md` (you own that one file in devnet-genesis).
