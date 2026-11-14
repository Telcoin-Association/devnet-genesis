# HD-2a API: the pure own-chain hold (`OwnChainOrder`) for HD-2b and HD-2p

Written by HD-2a. Branch `b7/hd2a` on base 45dce8947; commit: see `tasks/checkpoint-bench7-HD-2a.md`.
File: `crates/consensus/primary/src/order_hold.rs` (new), plus one `mod` line in `crates/consensus/primary/src/lib.rs`.
The module doc carries the rule, I1 to I3, the safety argument with DR-1807's wording correction, the GC-cut residual and what the module does not decide.

## Surface (all `pub(crate)`)

```rust
#[derive(Debug, Default)]
pub(crate) struct OwnChainOrder { /* newest own header's (round, floor) */ }
impl OwnChainOrder {
    pub(crate) fn plan<P, H>(&self, round: Round, parents: &[P], tracked: &BTreeMap<Round, H>,
        author: &P::Author) -> HoldPlan
    where P: ParentHeader, H: TrackedHeader<Digest = P::Digest>;
    pub(crate) fn record(&mut self, plan: &HoldPlan);       // every new header, an empty one included
    pub(crate) fn record_resent(&mut self, round: Round);   // restart re-propose and max-delay re-send
    pub(crate) fn forget(&mut self, round: Round);          // a round left `proposed_headers`
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct HoldPlan {
    pub(crate) held_workers: BTreeSet<WorkerId>, // lanes the header must leave queued
    pub(crate) blockers: BTreeSet<Round>,        // tracked digest-carrying headers not proven ancestors
    pub(crate) own_parent: bool,                 // parents cite the tracked own header of round - 1
    /* private: round, floor */
}
pub(crate) trait ParentHeader { type Author: PartialEq; type Digest: PartialEq;
    fn author(&self) -> &Self::Author; fn header_digest(&self) -> Self::Digest; }   // impl for Certificate
pub(crate) trait TrackedHeader { type Digest: PartialEq;
    fn header_digest(&self) -> Self::Digest;
    fn workers(&self) -> impl Iterator<Item = WorkerId> + '_; }                     // impl for Header
```

## Why these input shapes

The proposer calls `plan(self.round, &parents, &self.proposed_headers, &self.authority_id)` with what `propose_next_header` holds on M: `parents: Vec<Certificate>` (from `mem::take(&mut self.last_parents)`) and `proposed_headers: BTreeMap<Round, Header>`.
Nothing is cloned: the impls read `cert.origin()`, `cert.header().digest()` and `header.digest()` (both cached) and `header.payload().values()`.
A model test implements the two traits on integer structs (`u8` author, `u64` digest, `Vec<WorkerId>` payload), as the module's own tests do (`Own`, `Parent`, `Model` in `order_hold.rs`).

## Exact semantics (what HD-2p can model)

- `own_parent` is true iff `tracked` has `round - 1` and some parent has `author() == author` and `header_digest() == tracked[round - 1].header_digest()`. Round 0 has none.
- `floor` = the record's floor when `own_parent` and the record is for `round - 1`; `round - 1` when `own_parent` without that record; `round` otherwise.
- `blockers` = every tracked round below `floor` whose header names at least one worker; `held_workers` = the union of their workers. Tracked rounds at or above `round` are ignored.
- `record(&plan)` replaces the record with `(plan.round, plan.floor)`. `record_resent(r)` keeps a record already at `r`, otherwise sets `(r, r)`. `forget(r)` clears the record if it is at `r`, otherwise does nothing.
- This is the design's `unproven(n) = unproven(n-1) ∩ tracked` in closed form: equal while the tracked set only ever gains the newest header, more conservative otherwise.

Two deliberate differences from the design's text, both on the safe or neutral side:
- An empty tracked header is never a blocker. The design's restart record ("the tracked older headers") would list empty ones too; they name no lane, so only the `blockers` count differs.
- A tracked own parent with no record proves only itself. Read literally, the design's `unproven(n-1) ∩ tracked` with no record would hold nothing.

## Wiring notes for HD-2b

1. `lib.rs` has `#[cfg(test)] mod order_hold;` under the comment `// test-only until the proposer consults it (issue #1807)`. Delete the `#[cfg(test)]` line and the comment above it in the commit that makes the proposer call the module. Every non-test item is then live only if you use it: `plan`, `record`, `record_resent`, `forget`, the three `HoldPlan` fields, the two traits and their impls. An item you leave uncalled fails `dead_code` under `-D warnings`.
2. Take the parents before the drain (DR-1807 item 6), call `plan`, then drain with `plan.held_workers`.
3. `record(&plan)` can run in `propose_next_header` right after the plan, so the plan need not travel with the pending task: a plan reads a record only through a tracked own parent, so the record of a header that never becomes tracked is inert.
4. Call `record_resent(header.round())` for the restart re-propose (the `Some(header)` arm of `propose_next_header`) and for the max-delay re-send. It keeps an existing record and otherwise records "proves nothing", so `handle_proposal_result` need not tell the two re-send kinds apart (DR-1807 item 5).
5. Call `forget(round)` for every round removed from `proposed_headers`: the committed rounds and the retransmitted rounds of `process_committed_headers`, and `process_uncertified_header`. Safety does not depend on it; it keeps the record inside the tracked set.
6. `held` (digests left queued in held lanes) is a count over the queue, not part of the plan; `held_lanes = plan.held_workers.len()`, `blockers = plan.blockers.len()`.
