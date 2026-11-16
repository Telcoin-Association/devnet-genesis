# R1b — finish unit R1: the `epoch_record_recertify` switch goes

You continue unit R1. Read `tasks/bench8-agent-rules.md` ("Removal units (R1-R5)" is your contract; budget 35 tool calls, about 120 printed lines per call), then the brief `tasks/bench8/briefs/r1.md` (points 3-6 are what is left), then R1's checkpoint `tasks/checkpoint-bench8-R1.md`: it holds a map, from 500e21afa, of every site this commit must touch. Your own checkpoint: `tasks/checkpoint-bench8-R1b.md`.
Skills: `tn-rust-skills`, `tn-domain-epoch`.
Worktree `/home/drtnarg/coding/telcoin/tn-b8-uc`, branch `refactor/remove-bench-switches`, tip a5be61615 (R1's first commit removed the walk's switch; it did not touch `crates/node/src/manager/epoch_votes.rs` or `crates/types/src/test_hooks.rs`, so the map's line numbers there still hold; everywhere else `grep -n` first).

## What is left (from R1's hand-back)

- `crates/config/src/node.rs`: the field `epoch_record_recertify` (about `:418-442` at 500e21afa), its default, its `runtime_switches!` entry.
- `crates/node/src/manager/node.rs:1329`, `:1339`: the two readers.
- `crates/node/src/manager/epoch_votes.rs`: the `recertify` parameter and its branches; `Option<RetainedEpochVotes>` at `:155` (`manage_epoch_votes`) and `:542` (`handle_new_vote`) with `if let Some` sites at `:186`, `:229`, `:304`, `:446`, `:729` and `map_or(RoundKind::Current, …)` at `:185`, `:4461`. The value is always there once the switch is gone: the `Option` goes, unless removing it would make a kept branch read differently (then stop that item and say so).
- Test calls that pass `None` (`:2193`, `:2271`, `:2340`, `:2362`, `:2640`, `:2730`, `:2919`, `:3106`, `:3445`): sort each one: a fixture (gets an empty `RetainedEpochVotes`, listed as "kept, edited") or a test of the off behaviour (goes). Helpers and loops with a `recertify` parameter or variable: `epochs_voted_at_close` `:3678`, `queue_after_a_new_round` `:3776`, `conflicting_record_round` `:4401`, loops at `:3745`, `:4496`, `:4661`: keep the on case. Delete `test_switch_off_revotes_only_the_previous_record` (`:3735`).
- e2e: `fleet.rs` (the recertify entry of each list; 5 → 4), `epoch_close_forms.rs:206-212`, `:1062`, `epoch_record_walk.rs` (the `Arm::Recertify` switch entry), and the doc at `crates/types/src/test_hooks.rs:254`.

## The orchestrator's ruling on the e2e walk test

With re-certify always on, `test_uncertified_epoch_walked_past` would see epoch K re-certified at the close of K+2 while it asserts that K stays uncertified. Keep the test and its assertions; change only its plumbing: the Walk arm gives the vote-withholding hook enough rounds (`TN_TEST_WITHHOLD_EPOCH_VOTE_ROUNDS`, `crates/types/src/test_hooks.rs:246-258`; R1 suggests 16, read the hook to pick a number that covers every re-certify round the test's epochs can start) so that K stays uncertified, while the Recertify arm keeps `WITHHOLD_ROUNDS = 2`. The check `if arm != Arm::Recertify { assert_no_log(RECERTIFY_LOG) }` cannot hold for the Walk arm any more (its re-certify rounds run and end short): replace it for Walk with the strongest thing that is still true (for example: no record of K is certified on any node; if a log line or a metric marks a re-certify round that ended short, assert it appears) and say exactly what you asserted. Do not delete the walk test. You compile the e2e module (`cargo check --locked --all-targets -p e2e-tests`); the orchestrator runs it.

## Commit, gates, hand back

One commit (two if the `Option` removal is cleaner apart), compiling alone: subject like `refactor(node): vote rounds always keep signatures and re-vote one older uncertified record`; body: what goes, what stays, the walk test's plumbing change in one sentence, `Refs #1850`; last line `Topic: remove-bench-switches`.
Gates as the rules file says for `tn-config`, `tn-node`, `tn-types` if touched, and `e2e-tests` (check only): check, fmt, clippy, nextest. A cargo call may wait behind another job: that is normal; do not spend tool calls polling it; run it in the foreground of one call with a long timeout.
`git grep -n -w epoch_record_recertify -- crates` must return nothing when you are done.
Hand back as the rules file says, plus: whether the `Option` went; the verdict on each of the nine `None` calls; what the walk test asserts now.
