# PT-0 — port the switch machinery and the bench-6 observability to M

Unit: `PT-0` (node port unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-0.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt0`, branch `b7/pt0`, base **M = 45dce8947**. Domains: `tn-domain-epoch`, `tn-domain-consensus`. Plan rows: Track N's stack table rows 00, and "Port units".

## What this unit delivers

The first head of the staging stack, `feat/bench6-switches-obs` (PR 00): the machinery that lets a later topic add one runtime switch with one field, and bench 6's observability that is not tied to a topic. **No behaviour switch is added here**: every topic's PR carries its own field.

Source commits on the bench-6 tree (`/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only; `git -C … show <sha>`), in port order:

| # | bench-6 commit | subject | files | note |
|---|---|---|---|---|
| 1 | 3696d49f3 | feat(config): list the runtime switches in Parameters | `crates/config/src/node.rs` | port the MACHINERY only (the list/iteration of switches, its docs, its tests); it must compile and make sense with zero switches. The twelve fields came in later per-topic commits (ledger rows 3-14): none of them is ported by you. |
| 2 | 5b9f13b25 | feat(config): leave switches at their default out of a written parameters.yaml | `crates/config/src/node.rs` | keep the rule: a switch at its default is not written. |
| 3 | 9c91263e7 | feat(node): log the node switches line and export tn_node_switch gauges | `crates/node/src/manager/node.rs`, `crates/node/src/metrics.rs` | the `node switches` info line and the `tn_node_switch{name}` gauge; with zero switches the line is still logged once at start (the harness's image contract requires the message `node switches`). |
| 4 | 16695b20a | feat(primary): gauge how far behind a node enters an epoch | see `git show --stat` | observability, no switch. |
| 5 | bfc5611ab | fix(metrics): give the engine stage histograms sub-millisecond buckets | `crates/tn-metrics/src/recorder.rs` | M changed this file (≈40 lines) and added new histograms in #1834 (`tn_reth.block_{execute,signer_recovery,finish,hashed_state,state_root,overlay_extend}_seconds`, `persist_{save_blocks,commit}_seconds`): the bucket rule must cover the ones bench 6 named and say what it does for M's new ones (give them the same sub-millisecond buckets if they are per-block stage timings; report which). |
| 6 | c8e5ae7be | fix(primary): keep a digest's first receipt across a re-queue | `crates/consensus/primary/src/{metrics.rs,proposer.rs,tests/proposer_tests.rs}` | `proposer.rs` is byte-unchanged on M against the old base, so this should apply cleanly; it changes what a metric measures, not what a header carries. |

First establish what M did to each target file since the old base: `git -C /home/drtnarg/coding/telcoin/tn-b7-pt0 diff 165e3fe01 45dce8947 --stat -- <file>`; where a commit does not apply, re-apply its intent by hand against M's code and say so in the commit body's last sentence before the footer.
If any of the six turns out to be already in M in another form (the #1827 squash carried review follow-ups of the observability stack), drop it and record the evidence (`file:line` on M).

Commit footers: `Topic: bench6-switches` for 1-3, `Topic: bench6-obs` for 4-6.

## The switch machinery's contract (what later units rely on)

- Adding a switch = one `pub` field on `Parameters` with `#[serde(default …)]`, its `///` doc (what it changes, default, the issue), and one entry in the switch list; nothing else anywhere for the `node switches` line and the `tn_node_switch` gauge to show it.
- Bool and integer switches both appear in the line (`name=value`); the gauge exports 1/0 for a bool and the value for an integer (say exactly what bench 6 did for `quorum_exec_block_starved_rounds` and keep it).
- A unit test that fails when a field is added to the marked switch block without a list entry, if bench 6 had one; if it did not, add the cheapest honest version (for example a test over a `Parameters` serialized with every switch non-default).
- Write the note `tasks/bench7/briefs/pt0-api.md` (devnet-genesis; you own this one file there): the exact steps and code shape for a topic unit to add its switch field on your head (file, the marked block's begin/end comment lines, the list entry, the doc convention, the test to extend), in under 60 lines. Every later unit reads it.

## Tests and gates (through the slot wrapper; see the rules)

`cargo check --locked --all-targets -p tn-config -p tn-node -p tn-primary -p tn-metrics` (use the crates' real package names from their `Cargo.toml`), fmt check with the pinned nightly, clippy for the same packages, `cargo nextest run --locked` for the same packages (mind the tn-config quirk in the rules). The ported proposer tests of commit 6 run three times by name.
Then one `tn-domain-reviewer` (opus) on `git diff 45dce8947..HEAD` with domains epoch and consensus; fix or record.

## Hand back

As the rules say, plus: the six commits' new shas in order with the bench-6 sha each came from; what was dropped as already in M; the `node switches` line exactly as logged with zero switches; the path of `pt0-api.md`; which of M's new histograms got the buckets.
