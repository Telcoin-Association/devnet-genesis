# HD-4a — the test hook that breaks a validator's own chain on demand (`TN_TEST_OWN_CERT_DELAY_MS`), and a count of dropped cancel reports

Unit: `HD-4a` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-4a.md`. Budget: under 120k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-hd4a`, branch `b7/hd4a`, base **M = 45dce8947**. Domains: `tn-domain-consensus`. Topic slug: `digest-order-hold`. `Refs #1807`.

## Why

Issue #1807's defect needs a validator whose own header at round r is not among the parents of its header at round r+1 (its own chain breaks), so that the older header's batch digests are re-queued after newer ones were already drained. On a fleet this happens to far or slow validators; in a four-node local e2e test it almost never does. The e2e test of the fix (another unit, later) needs to produce it on demand, in both kinds the proposer distinguishes: `canceled` (the header never certifies and the certifier reports it canceled) and `committed` (the header certifies late, misses the next header's parent set, and is re-queued by a commit notice).
Design: `benchmark/private/bench7-prep/design/design-1807-own-chain-hold.md` §3's table row for `test_hooks.rs` / `certifier.rs` and §4 "e2e"; the delta read on M: `benchmark/private/bench7-prep/DR-1807/findings.md` (verdict 2: `report_canceled` at `certifier.rs` ≈ :781-801, called from ≈ :594, :653, :742, and its three ways of being dropped; "Changes to the design" items 1 and 11).

## What to build

1. **The hook**, in M's own test-hook pattern (`crates/types/src/test_hooks.rs`: read how the existing hooks are declared, read from the environment, cached and listed, ≈ :185-193 and :257-283, and how the node guarantees they are inert in production: follow that pattern exactly, including whatever startup line or refusal M has for a set hook; if M's hooks are compiled into release builds and only read from the environment, yours is too, and you say so plainly in the hand-back for the security review).
   - `TN_TEST_OWN_CERT_DELAY_MS=<ms>`: the certifier delays THIS node's own certificate by `<ms>`.
   - `TN_TEST_OWN_CERT_DELAY_STAGE=before_store|after_store` (default `after_store`): where the delay sits. `after_store` = the certificate is formed and stored, then held back from the path that makes it a parent candidate of this node's next header: the header certifies but misses its own next parent set → the `committed` kind. `before_store` = the delay sits before the certificate is formed or stored, long enough that the next own header is proposed first and the certifier cancels the older one → the `canceled` kind. Establish from `certifier.rs` on M where each point really is and whether each produces its kind; if `before_store` cannot produce a cancel without a second lever (e.g. the delay must exceed a timeout), say what value does and put it in the doc.
   - `TN_TEST_OWN_CERT_DELAY_EVERY=<n>` (default 1): apply to every n-th own header only, so a test gets a mix of intact and broken own chains.
   - Unset: byte-identical behaviour (no branch taken on the certificate path beyond reading a cached `Option`).
2. **A count of dropped cancel reports**, always on, no switch: DR-1807 found three ways `report_canceled` loses a report (the shutdown guard with no log; a full channel with a debug line; no subscriber, where `try_send` returns `Ok` silently). From `certifier.rs` count the ones the certifier can see: `tn_primary.uncertified_report_dropped_total{reason}` with `reason` = `shutdown` | `full` (inline `metrics::counter!` in the file's existing style; do not edit `crates/consensus/primary/src/metrics.rs`, which is in another unit's chain, and nobody edits `consensus_bus.rs`), and make the shutdown drop log one debug line like the full-channel one. The silent no-subscriber case cannot be seen from the certifier: say so in the doc comment.

## Files you own

`crates/types/src/test_hooks.rs` (your constants, reader and list entries only: another unit adds a different hook to this file later), `crates/consensus/primary/src/certifier.rs`.
Nothing else: no e2e module (the e2e unit HD-4b uses your hook), no `proposer.rs`, no `metrics.rs`.

## Tests

- Unit tests in the certifier's existing test module (find M's: `grep -rn "certifier" crates/consensus/primary/src/tests/ | head`): with the hook unset the certificate path is unchanged (M's tests pass untouched); with `after_store` the own certificate reaches the store at once and the parent path only after the delay; `EVERY=2` delays alternate headers; a parse error in a hook value is handled as M's hooks handle it.
- The drop counter: a full channel counts `full`; the shutdown guard counts `shutdown`.
- Hooks read process environment: follow M's way of testing them without racing other tests (an environment lock, an injected value, or a constructor parameter).
- Whole-package nextest for the primary and the types packages (mind the tn-types quirk in the rules); each new test three times by name.

## Gates and review

As the rules say; one `tn-domain-reviewer` (opus) on your diff, domain consensus: can the hook, when unset, change any timing or ordering; can a set hook make an honest node equivocate or sign two certificates for one round (it must only delay).

## Hand back

As the rules say, plus: the three variables' exact grammar; where each stage sits (`path:line`) and which re-queue kind it produces, with the delay a four-node local fleet needs for each; how production is protected from a set hook, in M's terms; the counter verbatim.
