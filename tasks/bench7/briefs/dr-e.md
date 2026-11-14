# DR-E — delta read: the epoch-record designs against the code at M

Unit: `DR-E` (read-only, opus). Rules: `tasks/bench7-agent-rules.md` ("What nobody but the orchestrator does", "Repos and worktrees", "Checkpoint, budget, scratch", "Delta reads …", "HAND BACK"). Checkpoint: `tasks/checkpoint-bench7-DR-E.md`. Budget: under 100k tokens.
No cargo, no edits to any repository, no commits. You write two files (same text) and your checkpoint.

## Why

Two hardening changes were designed from the bench-6 tree at 2df831e3c: `benchmark/private/bench7-prep/design/design-epoch-record-hardening.md` (A: the `final_state` check; B: the collector hardening; C: tests; D: units; E: risks).
They answer two findings of bench 6: `benchmark/private/bench6-r20261113-1351/E-3/findings.md` (nothing checks that an epoch record's `final_state` is the block where the epoch-closing calls ran) and `…/E-4/findings.md` (G1: an epoch the whole network leaves uncertified stops the record collector and the startup sync on every node; G2: a conflicting certified record on the collector path is only logged).
The code is now built on **M = 45dce8947** (`/home/drtnarg/coding/telcoin/telcoin-network-b7`, read-only). M rewrote the files the designs touch: #1834 added an unconditional `check_stored_record` guard in `crates/node/src/manager/node/close_epoch.rs` (+631 lines) and changed `run_epoch.rs` (+163); #1841 added a republish pass in `crates/state-sync/src/epoch.rs`; #1823 is nearby. Bench 6's own switch `epoch_record_state_check` (commit 42b2a6f39 on the old tree) does not carry.

## Questions (answer each from the code at M, with `file:line`)

1. **`check_stored_record` (#1834)**: what exactly it compares (which fields of the stored record against which local values), on which paths it runs (the build path in `write_epoch_record`, the stored-record path, epoch entry, restart replay), what it does on a mismatch (halt, error, log), and whether it is unconditional. Against design §A's `closing_block_check` (beacon root == `final_consensus.hash`; the header's nonce epoch; the 32-byte `extra_data` equal to the output's shuffle seed; optionally the registry's `blockHeight − 1`): which of the four comparisons M already makes, which it does not, and where the missing ones would go on M (the function and the line before `save_record` / before any committee read). Is the closing block's sealed header still available from the recent-blocks ring at that point on M?
2. **Switch**: the plan says "extend upstream's guard where it is unconditional, otherwise `epoch_record_state_check`". From (1): can the new comparisons be added to M's guard without a switch and still leave every existing test and the default behaviour unchanged except on a real mismatch? Recommend: no switch, a switch for the halt only, or a switch for everything, with the reason. (The bench runs want the check ON; the PR wants the smallest honest diff.)
3. **The `epoch record published` info line and the two counters** (`epoch_record_closing_block_check_total`, `epoch_close_identity_check_total`): where on M the record is saved and published, what is already logged there (level, fields), and whether M already logs `final_state`.
4. **The republish pass (#1841)** in `state-sync/src/epoch.rs`: what it republishes, when, to whom; does it already close gap G1 or part of it (an epoch nobody certified: does any node re-vote or re-publish its own uncertified record)? Does it change design §B's walk (`collect_epoch_records`: walk past an epoch the node holds as its own uncertified record; at most 16 gaps; a retry set) or the re-certify path (the close-time failsafe re-votes one older own uncertified record; `RetainedEpochVotes`)?
5. **The collector on M**: `collect_epoch_records` and the startup record sync: where they stop at an uncertified epoch on M (the old tree: `state-sync/src/epoch.rs:343-345`), what a `ConflictingRecord` does on M (design: fail-stop behind `epoch_record_conflict_halt`), what the `retrieved cert` lines carry (design: add `peer`, `signers`), and where the false `failed to reach quorum on epoch close` error is raised when the certificate is already held (`primary/src/network/mod.rs`, `epoch_votes.rs`).
6. **Can a fresh node's catch-up execute through an uncertified epoch?** A node that syncs from genesis (or an observer far behind) reaches epoch K whose record no peer has certified. On M: does execution replay need the certified record of K to cross into K+1 (committee source, the `check_stored_record` guard, the pack import), or does it proceed from consensus output alone? If it cannot proceed, design §B's "never walk past for a node without its own record" leaves that node stuck even after the hardening: say what would unstick it (the re-certify path making K certified later is the design's answer; confirm it reaches such a node).
7. **Tests on M**: which unit and e2e tests cover the stored-record guard and the collector today (names, files), so the E-units extend rather than duplicate. Does `crates/e2e-tests/tests/it/` on M have anything like bench 6's `epoch_close_forms.rs` (branch `b6/st-epoch-close-forms`, worktree `/home/drtnarg/coding/telcoin/tn-b6-u2`, read-only)?

## Read list (grep first; read in ranges)

- The design report above (all of it except the appended planning prompt); the two findings files' summaries (first 60 lines each).
- On M: `crates/node/src/manager/node/close_epoch.rs`, `crates/node/src/manager/node/run_epoch.rs` (the close and entry paths only), `crates/state-sync/src/epoch.rs`, `crates/consensus/primary/src/network/epoch_votes.rs`, `crates/consensus/primary/src/network/mod.rs` (the epoch-vote and failsafe parts), `crates/state-sync/src/lib.rs` (the startup sync entry).
- `git -C /home/drtnarg/coding/telcoin/telcoin-network-b7 log --oneline 165e3fe01..45dce8947 -- <path>` and `git … diff 165e3fe01 45dce8947 --stat -- <path>` show what moved; `git -C /home/drtnarg/coding/telcoin/telcoin-network-b6 show 42b2a6f39 --stat` shows what bench 6's own check was.

## Output

`/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench7-prep/DR-E/findings.md`, and the same text to `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench7-DR-E-findings.md` (write this one first; if the first path is refused, say so and the orchestrator copies it).
Shape: a verdict line per question, then the evidence; a last section **"Changes to the design"**: a numbered list per unit (E1 the check, E2 observability, E3 the collector walk and the conflict halt, E4 re-certify, E5 the e2e tests) with the file and line on M, the switch recommendation of question 2, and a list of what you could not determine.
If M already does what a unit was meant to add, say "E<n> is not needed on M" in the first lines of the file and of your hand-back, with the evidence.

## Hand back

Status; the verdict table (seven lines); the "Changes to the design" list; the switch recommendation; what you could not determine; token use.
