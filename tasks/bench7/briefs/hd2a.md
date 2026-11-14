# HD-2a — the hold's pure ordering module (`order_hold.rs`), ahead of its wiring

Unit: `HD-2a` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-2a.md`. Budget: under 150k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-hd2a`, branch `b7/hd2a`, base **M = 45dce8947**. Domains: `tn-domain-consensus`. Topic slug: `digest-order-hold`. `Refs #1807`.

## Scope: item 2 of `tasks/bench7/briefs/hd2.md`, and nothing else

Read `tasks/bench7/briefs/hd2.md` in full (the rule, the delta read's corrections, the invariants), the design `benchmark/private/bench7-prep/design/design-1807-own-chain-hold.md` §1 to §4 and §7, and `benchmark/private/bench7-prep/DR-1807/findings.md` (verdicts 1, 3, 6; "Changes to the design" items 1, 5, 6, 9).
You build ONLY:
- new file `crates/consensus/primary/src/order_hold.rs`: the pure `OwnChainOrder` (`plan`, `record`, `forget`, and whatever small value types they need: `HoldPlan { held_workers, blockers, own_parent }`), `pub(crate)`, `BTreeMap`/`BTreeSet` only, no I/O, no clock, no logging beyond none, no dependency on the proposer's private state: its inputs are plain values (the round, the parents' (origin, round, header digest) triples or the certificate type M's proposer already holds, the tracked own headers as (round → header digest, the workers its payload names), this node's authority id). Choose the input shapes so that (a) the proposer can call it with what `propose_next_header` has in hand on M (read `proposer.rs` ≈ :1011-1113, `proposed_headers` ≈ :148/:296, the parents' type) without cloning payloads, and (b) a model test can drive it with integers alone;
- its `mod` line (find where the primary crate declares `proposer` and add yours beside it; `#[allow(dead_code)]` is NOT allowed by the rules' no-suppression line: since nothing calls the module until the wiring unit lands, gate what is unused with `#[cfg(test)]`-reachable tests and, if the crate's lints still reject unused items, expose the type through one `pub(crate)` re-export the wiring unit will use and say exactly what you did);
- inline unit tests (`#[cfg(test)] mod tests` in the same file) for the rule alone, with rounds and workers as small integers: own parent present with an intact chain → nothing held; own parent missing → every tracked older header with digests blocks its lanes; `unproven` carried transitively across several rounds and cleared by `forget`; an empty header still records; a restart re-proposal's record; a max-delay re-send keeps the record; two lanes, one blocked; a round jump; `forget` of a round that was never recorded; the map's size is bounded by the tracked set.
- the module doc: the rule; invariants I1 to I3; why it is safe, with DR-1807's wording correction (an older own header that is not an ancestor of the next own header is ordered before the newer one or never, so overtaking comes only from the committed-kind re-queue); the GC-cut residual; what the module does NOT decide (timing, validity, what peers accept).

You do NOT touch `proposer.rs`, `metrics.rs`, `proposer_tests.rs`, `crates/config/src/node.rs` (three other units are in a serial chain on those files; the wiring unit HD-2b adds the switch field and calls your module).

## Gates

`cargo check --locked --all-targets -p <primary package>`, fmt check, clippy for the package, `cargo nextest run --locked -p <primary package>` (whole package), through the slot wrapper.
One `tn-domain-reviewer` (opus) on your diff, domain consensus: is the rule as coded exactly the design's rule with the delta read's corrections; can `plan` ever release a lane whose blocker is not an ancestor of the header being built.
If you find the rule itself wrong or incomplete (a scenario where following it still lets an older digest of a lane execute after a newer one, other than the GC-cut residual), STOP and hand back the scenario: a design change goes back to the user.

## Hand back

As the rules say, plus the module's public surface (signatures) and the input shapes you chose and why, also written to `tasks/bench7/briefs/hd2-api.md` (you own that one file in devnet-genesis; the wiring unit and the property-test unit read it).
