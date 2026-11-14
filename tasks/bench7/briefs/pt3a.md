# PT-3a — port the vote fix (`quorum_exec_block`, both forms) to M, with the review follow-ups

Unit: `PT-3a` (node port unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-PT-3a.md`. Budget: under 200k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt3a`, branch `b7/pt3a`, base = the integration head after PT-0 (the orchestrator creates it). Domains: `tn-domain-consensus`, `tn-domain-execution`. Plan rows: Track N's stack table row 05, "Port units".
Read `tasks/bench7/briefs/pt0-api.md` first: it says how a topic adds its switch field on PT-0's machinery.

## Background

Issue #1804: a header names an execution block (the author's view of the chain); a voter that has not executed that block refuses or delays its vote, so a fast executor's headers go uncertified.
Bench 6 fixed it behind two switches (units U1, U1b; briefs `tasks/bench6/briefs/u1.md`, `u1b.md`; design `benchmark/private/bench6-prep/design/design-node-fixes-for-bench-6.md`, the quorum-exec-block section; review `tasks/bench6/review/vote-starvation-report.md`):
- `quorum_exec_block: bool` — the header names a block a quorum has shown it executed, with a floor 8 outputs behind the author's own tip, instead of the own tip;
- `quorum_exec_block_starved_rounds: u32` — 0 = always-on (always the quorum-backed block); N > 0 = adaptive (the own tip until the author's headers went uncertified for N rounds, then the quorum-backed block; the window resets only after 64 consecutive certified tip headers).
Bench 6's four headline runs: always-on held certification at 20,000 IOPS and lost it on four validators at 50,000 IOPS; adaptive is compared in the report's §8. The form is decided after bench 7: **both forms are ported, both stay behind the switches, defaults off / 0.**

## Source commits (bench-6 tree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only), in port order

| # | bench-6 commit | what | files |
|---|---|---|---|
| 1 | 86755c450 | the switch fields | `crates/config/src/node.rs` (apply through PT-0's machinery: your two fields only) |
| 2 | d4be3a435 | ring helpers | `crates/consensus/primary/src/recent_blocks.rs` (byte-unchanged on M against the old base) |
| 3 | 5d7821dfb | both policies in the proposer | `crates/consensus/primary/src/proposer.rs` (byte-unchanged on M against the old base, but PT-0's commit 6 touched it: you are its next writer), `tests/proposer_tests.rs` |
| 4 | 14b55b04c | voter-side tests: the two voter cases hold with the switch off and on | NOT YOURS: `crates/consensus/primary/src/tests/network_tests.rs` changed by ≈734 lines on M with the vote-handler rework; a separate unit (PT-3v) re-expresses the two cases against M's handler after you. Do not touch that file. |
| 5 | 20858d28d | the adaptive window resets only after a streak of certified tip headers | `proposer.rs`, tests |

`git -C /home/drtnarg/coding/telcoin/telcoin-network-b6 log --oneline --grep='Topic: quorum-exec-block' 165e3fe01..2df831e3c` lists them; some commits of this topic carry no footer (ledger `tasks/bench6-cherrypick-ledger.md` rows 3, 17, 18, 39, 67). The e2e commits (8bd68e514, 31ef1149c, 56f66e160: `tests/it/exec_block.rs`) are NOT yours: a later test unit ports them.

## Follow-ups from the bench-6 review, to build here (each its own commit)

1. **D75 — clamp the named block to the epoch's opening block.** `tasks/bench6/review/vote-starvation-report.md` (grep `D75` there and in `tasks/bench6-upstream-followups.md:44`): the quorum-backed value and the floor must never name a block before the current epoch's first block. About ten lines plus a unit test at an epoch's first rounds (own tip fewer than 8 outputs into the epoch).
2. **Validate `quorum_exec_block_starved_rounds`** (the review's I5, `vote-starvation-report.md:203`): what happens today with a value that makes no sense with the switch off or an absurdly large value; add the validation the review asks for where `Parameters` are validated on M (or at the proposer's construction), with a test. A node must not start with a combination that silently does nothing: say what the node does instead (refuse to start with a clear error, or log a warning and treat it as documented).
3. NOT here: the superseded-refusal counter belongs to the voter's queue fix (`handler.rs`), unit PT-2 phase B. D76 (carry the adaptive window across epochs) is optional and not built.

## Invariants to keep (the reviewer checks these)

- Switch off: header contents byte-identical to M (a golden test over a fixed sequence of proposals if bench 6 had one; keep it).
- Determinism: the named block is a function of what the proposer has seen (certificates' execution info), never of wall-clock time; no HashMap/HashSet iteration decides it.
- The voter's rule is unchanged: a voter still only votes for a header whose named block it has executed and agrees with; the fix changes what the author names, not what a voter accepts.
- A mixed fleet (some nodes on, some off, some adaptive) stays one chain: nothing in the header's validity changes.
- Log fields and metrics of the topic exactly as bench 6 named them (`tasks/bench6-contract.md`, the quorum-exec-block row): the harness and the analysis scripts parse them (the per-header basis: own tip / quorum value / floor; the starved window state).

## Tests and gates

`cargo check --locked --all-targets -p <primary package> -p tn-config`, fmt check, clippy for the same, `cargo nextest run --locked` for the same packages (whole packages; mind the tn-config quirk), each new or ported timing-sensitive test three times by name.
`tn-domain-reviewer` (opus) on `git diff <base>..HEAD`, domains consensus and execution; fix or record.
Commit footer: `Topic: quorum-exec-block` on every commit; `Refs #1804`.

## Hand back

As the rules say, plus: the new shas with the bench-6 sha each came from; what the voter-side test unit needs from you (the fields a header carries for the named block, how a test builds a header under each form); the validation's behaviour in one sentence; every log field and metric of the topic verbatim; anything in M's vote-handler rework that changes what the fix can assume about voters (for the form comparison in bench 7).
