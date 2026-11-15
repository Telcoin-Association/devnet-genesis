# BF-04b — head 04's e2e commit on today's main (the uncertified-epoch tests), without the conflict-halt switch

Unit: `BF-04b` (e2e unit, opus; load `tn-rust-skills` and `tn-write-e2e`). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", the e2e lane rule, plus the common sections). Checkpoint: `tasks/checkpoint-bench7-BF-04b.md` (a `status:` header and finished sections, rewritten after each section; on start read it and continue). Budget: under 150k tokens.
Worktree and base: in your launch prompt (a branch at today's `main` 33b727fce plus heads 00-03 and head 04's 24 node commits; do not change them). Test code only: if a test needs a production change, stop and hand back.

## What exists

On the old base, head 04's last commit is `ca258b37c` `test(e2e): an epoch the network never certifies, walked past and re-certified`: `crates/e2e-tests/tests/it/epoch_record_walk.rs` (three tests), `crates/e2e-tests/tests/it/fleet.rs` (shared helpers and the stack's switch lists as of head 04), one `mod` line in `tests/it/main.rs`. Its brief was `tasks/bench7/briefs/e5b.md`; the restructuring that gave it `fleet.rs` is in `tasks/checkpoint-bench7-E2E-R.md`.
The node part under you no longer has the switch `epoch_record_conflict_halt`, its threshold, the counter `tn_state_sync.epoch_record_conflicts_below_halt_threshold_total` or the phrase `epoch record conflict halt:`. What exists instead, verbatim, is in `tasks/checkpoint-bench7-BF-04a.md` ("Names at the tip" in its Part 2 section): two switches (`epoch_record_collect_past_uncertified`, `epoch_record_recertify`) beside head 02's `vote_queue_fix`; on a validated conflicting certified record the collector logs an ERROR line starting `epoch record conflict:` (ending "…this node stops; do not delete its chain data before the cause is known"), counts `tn_state_sync.epoch_record_conflicts_total`, and upstream's stop follows: ERROR `a certified epoch record from peers conflicts with this node's own record for the epoch: this node's execution diverged from the certified chain, stopping the node`, counter `tn_epoch.final_state_mismatches_total`. A vote round that finds a conflict logs a line ending `we have forked!` and stops the node.

## The job: ONE commit, `ca258b37c` picked and made right for this base

1. `git -c rerere.enabled=false cherry-pick ca258b37c`; resolve; amend your own fresh commit until it is right (nothing here is pushed).
2. The switch lists in `fleet.rs` (off and on) name exactly the switches the node at this head has; the assertion on every node's `node switches` line still fails on a switch the lists do not name and on a listed switch the line lacks.
3. Fatal lines (no node may log them in any run of any test): the list gains upstream's stop line above and the evidence prefix `epoch record conflict:` (every conflict now stops the node, so the prefix is fatal); the halt phrase and the "non-halting conflict line" distinction go. One list, in `fleet.rs`, used by the three tests; later heads' test files will import it: keep its name and visibility as they are if you can, and say what changed.
4. Counter assertions: `tn_state_sync.epoch_record_conflicts_total` and `tn_epoch.final_state_mismatches_total` are 0 on every node at the end of every test (scrape names: the exporter renders the dot as an underscore; follow the file's existing scrapes); the below-threshold counter's assertion goes.
5. The three tests' meaning is unchanged (the gap with every switch off; the walk; the re-certify): do not weaken an assertion; if one of them only held because of the halt switch, say which and what now holds it.
6. The module docs and the commit body say what the tests do at this head; no sentence about a halt switch or a threshold. Body in plain prose, `Refs #1850`, then `Topic: epoch-record-collector-hardening` as the last line; no attribution of any kind.

## Gates

- `cargo +nightly-2026-03-20 fmt --all -- --check`.
- Through `tasks/bench6/cargo-slot.sh`: `RUSTFLAGS="-D warnings -D unused_extern_crates" cargo check --locked --all-targets -p e2e-tests`, `cargo +nightly-2026-03-20 clippy --locked --all-targets -p e2e-tests -- -D warnings`.
- `git grep -n 'conflict_halt\|below_halt_threshold\|conflict halt:\|keeps its own record' HEAD -- crates` prints nothing.
- The three tests ONCE through the lane, in one job: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh cargo nextest run --locked -p e2e-tests --test it --run-ignored all --no-fail-fast -E 'test(/^epoch_record_walk::/)'` (take the exact invocation from how `tasks/bench7/orch-top-e2e.sh` runs the stack's tests; log under `<worktree>/target/tmp/bf04b-walk.log` with an `EXIT=` last line). The lane is the machine's one e2e slot and may wait long: never wrap it in a short timeout, never end your turn while your job runs or waits, never kill a process you did not start (your own test's nodes excepted). A failure is diagnosed from the node logs (`tn-debug-e2e` skill) before anything changes; if a test shows the node part not doing what its notes say, that is a finding: keep the logs, stop and hand back.

## Hand back (a summary)

The commit id; what differs from `ca258b37c` and why; the lists as they are now (switches off / on, the fatal lines, verbatim); the gates' results with log paths and the three tests' wall-clock; anything the node logged in the runs that a maintainer should know; what later heads' e2e files (`exec_block.rs`, `epoch_close_forms.rs`, `digest_order_hold.rs`) must change to compile and pass on top of yours (names they import that changed).
