# HD-3 — count what the orphan re-pool does with each transaction at an epoch start

Unit: `HD-3` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-3.md`. Budget: under 120k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-hd3`, branch `b7/hd3`, base = the integration head with unit E1's commits in it (E1 was `close_epoch.rs`'s first writer; you are its second: the orchestrator creates the worktree). Domains: `tn-domain-epoch`, `tn-domain-worker`. Topic slug: `digest-order-hold`. `Refs #1807`.

## Why

Headers proposed after an epoch's last committed output never commit; their batches stay in the node's own-batches cache and `orphan_batches` re-pools their transactions at the next epoch's start (`crates/node/src/manager/node/close_epoch.rs`; called from `run_epoch.rs` before any batch builder starts).
Bench 6 counted 185 batches that never executed across its runs and could not say what happened to their transactions: a re-pool refusal is logged at debug only, per transaction, and nothing is counted.
The delta read on M (`benchmark/private/bench7-prep/DR-1807/findings.md`, verdict 4, "Changes to the design" item 10, and the first "could not determine" item) adds a suspicion worth a counter: the batch builder bumps the pool's account state for every sealed batch, so if that bump survives to the re-pool, an orphaned transaction that NEVER executed would be refused as nonce too low and lost without a trace. Only a refusal count split by reason can show it on a fleet.

## What to build — observability only, no switch, no behaviour change

In `repool_batch_txns` / `recover_orphan_batches` / `orphan_batches` (DR-1807's anchors: ≈ :132-172, :178-217, :236-288 before E1's edits; `grep -n` on your base):
1. `tn_node.orphan_txs_total{result}` (inline `metrics::counter!` in the style `crates/node/src/manager/epoch_votes.rs` uses for `tn_node.*`; do NOT edit `crates/node/src/metrics.rs`): `result` = `repooled` | `invalid` (failed to decode or recover) | `refused_nonce_too_low` | `refused_other`. Classify a refusal by the pool's own error type, never by matching message text; if the pool's error does not let you tell nonce-too-low apart, say so and split what it does allow.
2. `tn_node.orphan_batches_total{path}`: `path` = `own_worker` | `worker0_fallback` (≈ :139-144) | `non_validator` (the disbursal path ≈ :259-280), so the fleet can tell which path ran.
3. The existing summary line `Finished processing orphaned batches` (≈ :214-215) gains the counts as fields (`batches`, `txs_repooled`, `txs_invalid`, `txs_refused_nonce_too_low`, `txs_refused_other`), keeping its message text and existing fields; its level stays what it is. The per-transaction debug lines stay.
4. A doc comment on the function stating what a `refused_nonce_too_low` means in each case (an already-executed transaction, which is expected; or a never-executed one refused because the pool's view of the sender's nonce ran ahead, which would be a loss) and that the counter alone cannot tell them apart: the fleet reads it against the generator's unlanded list.

Do not change what is re-pooled, in what order, or what happens on a refusal.

## Files you own

`crates/node/src/manager/node/close_epoch.rs` (the three orphan functions and their tests only; E1's record-path code above and below is not yours).

## Tests

In the file's test module: a batch whose transactions all re-pool; one with an undecodable transaction; one refused as nonce too low (an executed nonce); one refused for another reason (pick one the test pool can produce: an underpriced replacement, a full pool); the worker-0 fallback; the summary line's fields; the counters by a local recorder as M's metrics tests do.
Whole-package nextest for the node package; fmt; clippy.
One `tn-domain-reviewer` (opus) on your diff, domains epoch and worker: is any count taken on a path that can run twice for the same batch (a restart, a retry), and does the classification hold for every pool error variant on M.

## Hand back

As the rules say, plus: both counters and the summary line verbatim; how a refusal is classified (`path:line` of the error type); what you learned about the first "could not determine" item of DR-1807 (does the sealed-batch bump of the pool's account state survive to the re-pool: answer from the code if you can, otherwise say what would show it).
