# HD-4b — e2e for the own-chain hold (#1807): every accepted transaction lands once, with no resend, while one validator's own chain keeps breaking

Unit: `HD-4b` (e2e unit, opus; load `tn-rust-skills` and `tn-write-e2e`). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", the e2e lane rule, plus the common sections). Checkpoint: `tasks/checkpoint-bench7-HD-4b.md`. Budget: under 200k tokens.
Worktree and base: in your launch prompt (the integration head with the hold wired in: switch `digest_order_hold`, and with `tests/it/exec_block.rs` in it). Domains: `tn-domain-consensus`, `tn-domain-worker`. Topic slug: `digest-order-hold`. `Refs #1807`.
Test code only. If a test needs a production change, stop and hand back.

## Why

Issue #1807: a proposer drains its workers' batch digests into header N; if N is not certified (cancelled by a newer own header) or not committed, its digests are re-queued AFTER header N+1 already drained newer digests of the same worker. A sender's transactions then execute out of nonce order: the later one fails ("nonce too high") and is lost unless the sender resends. Bench 6 measured it in four runs (far validators, whose own certificate arrives late, lose the most).
The fix (`tasks/bench7/briefs/hd2.md`, `hd2-api.md`; design `benchmark/private/bench7-prep/design/design-1807-own-chain-hold.md`): with `digest_order_hold` on, header N drains no digest of a worker named in the payload of an older own header that is not proven to be N's own-chain ancestor. Header contents only: no timing, wire or validity change; switch off = main's drain. A model test (100,000 schedules) found no order break with the hold on; one residual is known and accepted: an own header cut off by garbage collection from a commit that includes its descendant (`tasks/checkpoint-bench7-HD-2c.md`).
What exists for you:
- The hook that breaks a validator's own chain on demand (`tasks/checkpoint-bench7-HD-4a.md`): `TN_TEST_OWN_CERT_DELAY_MS=<ms>`, `TN_TEST_OWN_CERT_DELAY_STAGE=before_store|after_store`, `TN_TEST_OWN_CERT_DELAY_EVERY=<n>` hold back the validator's OWN certificate in its certifier, so its header at round r is not a parent of its header at r+1 (what a far validator sees on a fleet). Read the grammar and each stage's effect in `crates/types/src/test_hooks.rs` on your base; `before_store` produces cancelled headers (the cancel path), and the commit path is exercised when a held certificate is committed late or skipped: establish from a first run which stage and delay give BOTH kinds, and say so.
- The observability (`tasks/bench7/briefs/hd1-api.md`): per-worker sequence numbers on queued digests; `tn_primary_requeued_out_of_order_total{cause}`; `own_parent`, `held`, … on the `header proposed` line; the `proposer stopped` line; the hold's `tn_primary_headers_held_total`, `tn_primary_digests_held` (names verbatim in that note and in the hold unit's hand-back, `tasks/checkpoint-bench7-HD-2b.md`); the certifier's `tn_primary.uncertified_report_dropped_total{reason=shutdown|full|unsubscribed}`; the orphan re-pool counters `tn_node_orphan_txs_total{result}` (`tasks/checkpoint-bench7-HD-3.md`).
- The load: bench 6's lost-transaction test (bench-6 tree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, read-only, `crates/e2e-tests/tests/it/sealed_txs.rs`: `SenderState`, `run_sender`, `run_load_across_boundary`, `assert_exactly_once`, `stuck_diagnosis`, the block and metrics helpers) drives many senders with consecutive nonces and NEVER resends. That file is not ported (its switch no longer exists): copy only the load and checking helpers you need into your file, re-expressed on this base's scaffold (`tasks/bench7/briefs/pt1-api.md`); reuse what `tests/it/exec_block.rs` and `tests/it/common.rs` already export instead of copying where they fit.

## The tests (new file `crates/e2e-tests/tests/it/digest_order_hold.rs`, ONE `mod` line in `tests/it/main.rs`)

Four validators as processes; the hook on ONE validator (the "far" one); a second member slowed by the engine's execution-delay hook so that the vote form matters (as `exec_block.rs` does); senders spread over all four validators' RPC with consecutive nonces, enough per sender that one sender's transactions fall into different batches of the same worker; the load runs across an epoch boundary. One shared driver, four tests:
1. `test_hold_keeps_every_transaction_adaptive`: `digest_order_hold true`, `quorum_exec_block true`, `quorum_exec_block_starved_rounds 4`, `vote_queue_fix true` (and the three record switches on, as the bench 7 arm has them).
2. `test_hold_keeps_every_transaction_always`: the same with `quorum_exec_block_starved_rounds 0`.
3. `test_hold_survives_a_kill_of_the_far_validator`: one form (say which and why), the hooked validator is killed (SIGKILL) under load and restarted on its datadir with the same overrides; the load to the other three continues; senders that were talking to the killed node are accounted for exactly (accepted before the kill and landed; accepted and orphaned: what the orphan counters say; refused: not accepted).
4. `test_without_the_hold_the_far_validator_reorders` (control: `digest_order_hold false`, everything else as test 1): `tn_primary_requeued_out_of_order_total` > 0 on the hooked validator. Do NOT assert a lost transaction (whether an out-of-order re-queue costs a transaction depends on which senders' digests it hits): report how many were lost in each run.
Assertions with the hold on (tests 1 to 3), all read from the nodes:
- every transaction a node accepted lands exactly once, with no resend by the test (the exactly-once check over the whole chain at the end);
- `tn_primary_requeued_out_of_order_total` is 0 on every validator for every cause that the hold covers (the note says which causes exist; a `stale_resend` / order-unknown counter is a different thing: report it, do not assert it);
- no execution failure for a nonce ahead of the account's nonce on any validator (bench 6's `nonce_too_high`: find how this base exposes it: an engine counter, a log line, or the receipts' absence; say which you used);
- the hold was exercised: `tn_primary_headers_held_total` > 0 on the hooked validator, and its re-queues happened through BOTH paths (cancelled and committed kinds > 0, by the counters the note names); `held` appears on its `header proposed` lines;
- all four validators hold the same block hashes at equal heights at the end, across the epoch boundary; no node logged a fatal line (the shared list in `exec_block.rs`);
- every node's `node switches` line carries the keys with the values the test set;
- the orphan counters are consistent with what the test saw at the epoch boundary and at the kill (state the rule you assert);
- record (do not assert) `tn_primary.uncertified_report_dropped_total` by reason: a `full` drop means a cancelled header's digests came back only through the commit notice; the exactly-once check must hold anyway.
Cost of the hold, reported per test (the bench 7 analysis will want the same numbers from the fleet): headers held and digests held on the hooked validator, how long a lane stayed held (rounds, from the `header proposed` lines), and the hooked validator's throughput share against test 4's.

## One line each in `exec_block.rs` (its own commit, first)

`tests/it/exec_block.rs` keeps the stack's switch lists (`STACK_SWITCHES_ON`, `STACK_SWITCHES_OFF`) and its `assert_switches` FAILS when a node's `node switches` line shows a switch the lists do not name. On your base the node has `digest_order_hold`, so add it at the end of both lists (`true` / `false`) before anything else, in a commit of its own (`test(e2e): list digest_order_hold among the stack's switches`), and run `exec_block::test_mixed_switch_fleet_is_one_chain` once through the lane to show the file's tests still pass with the hold on in the switched nodes. Change nothing else in that file.

## Stop rule

If, with the hold ON, a run shows an out-of-order re-queue of a covered cause, a transaction lost or landed twice, or validators on different blocks: that is a finding about the production code (or the model's known residual: check the garbage-collection case first, `tasks/checkpoint-bench7-HD-2c.md` §7). Do not bend the test. Keep the run's logs, stop, and hand back with the timeline (which header, which worker lane, which sequence numbers, which path) and `path:line` of the code you believe responsible. The orchestrator takes it to the user.

## Running e2e tests (the lane rule)

Every `-p e2e-tests` test run through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh <cmd…>`; other cargo through `tasks/bench6/cargo-slot.sh`. One e2e job on the machine at a time: batch your runs (logs under `<worktree>/target/tmp/hd4b-*.log`, an `EXIT=` last line each). Never wrap cargo or the lane in a short timeout; never end your turn while a job of yours runs or waits in the lane; never kill a process you did not start (your own test's validators excepted).
Each test once while you build it; each three times at the end. A failure is diagnosed from the node logs (`tn-debug-e2e` skill) before anything changes.

## Gates and review

`cargo check --locked --all-targets -p e2e-tests`, the fmt check, clippy for the package. One `tn-domain-reviewer` (opus) on your diff, domains consensus and worker: can tests 1 to 3 pass with the hold silently off or the hook silently unset (they must fail then: say which assertion fails); does the exactly-once check cover every accepted transaction of every sender, the killed node's included; does test 4 prove the control (the same fleet, the same hook, only the switch differs).
Commit(s): `test(e2e): the own-chain hold keeps every accepted transaction while a validator's chain breaks`, body in plain prose, `Refs #1807`, then `Topic: digest-order-hold` as the last line; no attribution of any kind.

## Hand back

As the rules say, plus: the hook settings used and what each produced (cancelled / committed re-queues per minute on the hooked validator); per test and run: accepted, landed, lost, duplicated, out-of-order count, headers held, digests held, the drop counter by reason; test 4's losses; the hold's cost figures; wall-clock per test; which form the kill test uses; anything in the node logs a maintainer should know.
