# Topic review: pipelined-persist (#1800, switch `pipelined_persist`)

Reviewed 2026-11-11. Code at `/home/drtnarg/coding/telcoin/tn-b6-u0c`, branch `b6/pipe-stack-2`. The diff is the 18 commits listed in the scope file, `d91d65d3e..86956df51`. Line numbers are at 86956df51. A 19th commit on the same topic, d30bb1809, landed on the branch during the review. It adds 4 lines that read the persist-delay hook when the environment is created, and the report covers it under F3 and 2a. It is not in the scope file's list.

How it was done:
- The repository's code review (`tn-review`) and its security evaluation (`tn-security-eval`) ran as two independent sub-agents. The security evaluation started 7 of its agents: consensus safety, state transitions, DoS vectors, determinism, nemesis logic audit, DREAD, STRIDE. Contract safety, crypto correctness and dependency audit were not started: the diff is Rust only and changes no `Cargo.toml`.
- I read the non-test core myself: `persister.rs` lines 1-1066, `lib.rs` lines 370-921, and the diffs of `payload_builder.rs`, `output_overlay.rs`, `execution.rs`, `env/mod.rs` and `test_hooks.rs`.
- I diffed the base `run` body against `run_sequential`.
- I checked every finding that carries the verdict against the code and the vendored reth.

Verification was not isolated per finding. In both skills the verifier had no Agent tool, so it checked the findings itself instead of starting one checker per finding. For that reason I re-checked F1, F4, the mixed-fleet vote path, the image build line and the identity of the sequential path myself.

## Verdict: APPROVE WITH FOLLOW-UPS

There is no Critical, High or Medium finding, so the go/no-go rule (no open High) is met. No code has to change before the benchmark image. The follow-ups are all for the upstream PR: two Low findings and ten Info findings.

Three checks on how the image is built and run:
1. **Image build.** Build the image the way `etc/Dockerfile:50` does: `cargo build -p telcoin-network --bin telcoin-network --release`, with no `CARGO_FEATURES`. That build leaves out `tn-types/test-utils`, so `persist_delay()` is the constant `None`. A workspace-root build or the e2e build has that feature, and then every node reads `TN_TEST_PERSIST_DELAY_MS`, switch-off nodes included, with no cap on the value. Make sure the variable is unset on the nodes either way (F3).
2. **Bench analysis.** Count the `pinning the output overlay failed - next output waits for the commit` warnings on each pipelined node. Each one marks a cycle that ran sequentially, and no metric counts them (F6).
3. **Mixed window.** Do not measure during the mixed window of a rolling restart. Under persist-bound load, pipelined proposers can wait for votes from the sequential half (2b).

## Findings, most severe first

### F1. Low, CONFIRMED: a dead commit task plus a failed head read rolls a durable output out of memory
- **Where:** `crates/engine/src/persister.rs:402-419` (the `lookup_head().is_ok_and(..)` at :408-409), then `settle` at :552-556.
- **Sequence:**
  1. Output N's commit task panics after `provider_rw.commit()`, for example in the announce or the finalize. The oneshot returns `RecvError`.
  2. `on_commit_done` asks `lookup_head()` whether N is durable. If that read fails, `is_ok_and` gives `false`, so N is classed as `FailureKind::Persist` and queued for rollback (`Slots::commit_failed`, :985).
  3. `settle` takes N's blocks out of reth's in-memory chain and sets the canonical head back to N-1.
  4. The DB holds N. The `recent_blocks` ring may hold N too, if the announce at `payload_builder.rs:538` was sent before the panic.
  5. The reported error is `ChannelClosed`.
- **The module's own rule:** this breaks the module's rule that a durable block is never rolled back (`persister.rs:20`).
- **Panic on the engine task:** reth's `NodeConfig::lookup_head` calls `expect` when the header is missing (`vendor/reth/crates/node/core/src/node_config.rs:366-368`). On a database in that state, the call panics on the async engine task instead of returning `Err`.
- **Impact:** memory only. The node halts, and a restart rebuilds from the DB. Nothing is persisted wrongly and nothing forks. Reaching it takes two faults, and no test reaches this branch.
- **Fix:** give `CommitSlot` an `Arc<AtomicBool>` that the commit task sets as soon as `persist_output_with_retry` returns `Ok`, and read it on `RecvError` instead of the DB. Alternatively, probe with `database_provider_ro()?.block_hash(tip.number)? == Some(tip.hash())`, and on a probe error do not roll back. Add a test-utils hook that panics the commit task once before and once after the persist.
- **When:** before the upstream PR. Not needed for the image.
- **Found by:** both sub-agents and my own read.

### F2. Low, CONFIRMED: no test reaches the I/O-side fail-closed guards
- **What:** only the `Slots`-table versions are tested; for example, `test_dispatch_refuses_output_not_built_on_durable_tip` calls `slots.dispatch`. I searched every test module of the topic, and none reaches these branches or their messages:
  - the three checks in `take_seed` (`persister.rs:294-307`);
  - the refusal when the pinned snapshot is not at the durable tip (:460-468);
  - the pin-error fallback, design row F6 (:469-478);
  - the `RecvError` arm (:402-419, see F1);
  - the engine's `drain_refused` for an out-of-order output (`lib.rs:641-668`).
- **Why it matters:** these are the guards for I1, I3, I6 and I11 at run time. They are not in the scope's list of accepted test gaps.
- **Fix:** tests only.
  - A test-utils "fail the next pin" hook, with the chain afterwards equal to the sequential engine's.
  - An engine test that feeds a duplicate consensus number: the engine drains, then returns `PipelineInvariant` with the durable prefix intact.
  - The commit-panic hook from F1.
  - An inline test that sets a mismatched `carry` before `start`.
- **When:** before the upstream PR.

### F3. Info, CONFIRMED: the persist-delay test hook is gated more loosely than its doc says
- **Where:** `crates/tn-reth/src/env/execution.rs:503-505` reads `tn_types::test_hooks::persist_delay()` on every persist, in both switch modes, with no `tn-reth` feature gate. d30bb1809 adds one more read at `env/mod.rs:274`.
- **What the doc says:** at `crates/types/src/test_hooks.rs:193` and `:199-201` it still says "the reth side applies it only with `tn-reth/test-utils`". That stopped being true at 86956df51.
- **Consequence:** any binary built with `tn-types/test-utils` slows every persist by whatever `TN_TEST_PERSIST_DELAY_MS` says, sequential nodes included, and the value has no upper bound.
- **Fix:** correct the doc and clamp the value (for example to 60 s).
- **Before the image:** check 1 above. With the Dockerfile build, the hook is the constant `None`.

### F4. Info, CONFIRMED and re-checked: seeded and unseeded builds can emit different `TrieUpdates`, with the same root and the same rows written
- **Where:** `crates/tn-reth/src/env/output_overlay/storage_cursor.rs:106-128`. When no overlay layer settles the question, `is_storage_empty` falls back to the anchor database's raw rows (:127).
  - A seeded build of N+1 reads the DB as of N-1 under N's runs.
  - An unseeded build reads the DB as of N.
  - Whether a build is seeded depends on timing (`persister.rs:165`, :858-860).
- **Example:** N zeroes every slot of a contract, and a block of N+1 writes one of those slots and resets it.
  - Seeded, the DB at N-1 still has raw rows, so reth's root walks the trie and finds no nodes to remove.
  - Unseeded, the DB at N has no rows, so the root returns `StorageTrieUpdates::deleted()`.
- **Same root:** both give `EMPTY_ROOT_HASH`.
- **Same rows:** `deleted()` wipes the account's rows (`vendor/reth/crates/trie/db/src/trie_cursor.rs:129-130`), and the walk deletes the nodes it saw, which are the DB-at-N trie the overlay represents. So the rows written are identical.
- **Not new:** `storage_cursor.rs` is unchanged by this topic (last changed in #1382). The same choice already depends on where an output boundary falls in the sequential engine. Pipelining only makes it depend on timing too.
- **What is wrong:** the doc at `output_overlay.rs:156-158`, which says the overlay keeps "Reth's exact choice between a deleted-trie marker and individual node removals", is not true for a seeded build.
- **Fix:**
  - Add a fixed regression test for this example, with N held in the commit slot, that compares block hashes and `trie_tables_digest` against the sequential oracle. The proptest reaches this case only by chance.
  - Reword the doc to "same root and same rows written".
- **When:** before the upstream PR.
- **Severity:** the security evaluation raised this as Medium. Its verifier and I downgraded it, because nothing consensus-visible differs.

### F5. Info: D45 is slightly understated
- **The pinned transaction's lifetime:** the read transaction is opened when N is dispatched (`persister.rs:449`). It then stays alive in two places:
  - in `carry`, until a seeded N+1 takes it (:305);
  - in N+1's build scope, until `build_output` returns.
- **Why the bound is a sum:** N+1 may start at any time before the engine handles N's commit. So the transaction can live for N's whole commit task (persist, announce and finalize) plus N+1's build.
- **How D45 is wrong:** libmdbx's 5-minute read-transaction timeout can therefore trip when that sum passes 5 minutes, even if each part is under it. D45 says "a build or persist longer than 5 minutes".
- **Impact:** irrelevant at bench timings (seconds).
- **Fix:** correct the D45 text in the PR.

### F6. Info, CONFIRMED: observability gaps in pipelined mode
- `built_at` is stamped on the engine task (`persister.rs:342`), not when the build ends. So `persist_wait_seconds` and `persist_wait_ms` leave out the time a finished build waits while the biased select serves other arms. Treat them as a lower bound in the bench analysis.
- `tn_engine_built_height` (`lib.rs:700`) is never lowered after a rollback.
- A failed pin only logs a warning (:471-476), with no counter.
- The settle line (:544-551) has no error, failure kind or height range.
- In pipelined mode the commit task logs "persisting executed consensus output failed - rolling back in-memory advance" (`payload_builder.rs:529`), but the rollback happens later in `settle`.
- **Fix:**
  - stamp the build's end on the build thread;
  - reset `built_height` to the durable tip when a failure settles;
  - add `pipeline_pin_failures_total`;
  - add `error`, `kind` and the rolled-back output numbers to the settle line;
  - give the pipelined path its own persist-failure message. Keep the sequential text unchanged.
- **When:** before the upstream PR.

### F7. Info, CONFIRMED: a panicking build leaves its partial blocks in memory
- **Where:** `unpersisted` is filled only when a build succeeds (`persister.rs:322-324`), and `settle` rolls back only what is listed there (:533-557).
- **What happens:** a build that panics mid-output ends in `RecvError`, and its partial blocks stay on reth's in-memory chain. The build's own `?` exits that skip the rollback exist in the base as well.
- **Impact:** memory only. The node halts.
- **Fix:** in `settle`, always set the canonical head to `durable` and drop every in-memory block above it.
- **When:** before the upstream PR.

### F8. Info, CONFIRMED: refused outputs, and a design assertion that was not built
- **Accepted behaviour, stated here for the PR:** a duplicate or out-of-order consensus number makes a pipelined node drain and halt (`check_order`, `persister.rs:871-878`; `lib.rs:641-668`), where the sequential loop would build it again. This is the accepted U12b note ("a stale output halts a pipelined node"), and only invalid input reaches it, because replay forwards strictly `parent+1`.
- **New:** the refused output's consensus number is not logged (`lib.rs:648-653` logs only the error).
- **New:** the design's T4 debug assertion (`report.parent == durable`) is not implemented. The anchor check at dispatch (`persister.rs:922`) covers it.
- **Fix:** log the refused output's consensus number, and state both points in the PR text.

### F9. Info: the wording of design invariant I9 is too strong
- **The claim:** I9 says the pipeline never rolls back while a slot is busy. That is true for `settle` (`persister.rs:1008`).
- **The exception:** a failed build rolls back its own blocks on the build thread (`payload_builder.rs:431`, through :888-896). That can run while N's commit task is in `finalize_block` (`execution.rs:422-438`).
- **Why it is safe:** both orders end the same way, with no blocks in memory above N and the head at N's tip; see 2g.5.
- **Fix:** correct I9 and the `finalize_block` doc (`execution.rs:411-421`).

### F10. Info: new synchronous work on the async engine task (switch on)
- **What moved:** these now run inside `start` and `next_event` on the tokio task:
  - `pin_output_overlay` (`persister.rs:449`): one read transaction and two point reads;
  - `lookup_head` (:409);
  - `rollback_in_memory_output` in `settle` (:552), which runs only once both slots are idle;
  - the last drops of a committed output's blocks (:365-369).
- **Cost:** microseconds each.
- **Fix:** optional. Pin on the blocking pool, or note it in the `run_pipelined` docs.

### F11. Info: the build can read through reth's historical provider
- **When:** between N's database commit and `finalize_block(N)`, N+1 resolves its parent state from N's in-memory blocks over a historical provider at N-1.
- **Why it is correct:** TN prunes nothing.
- **Fix:** extend the archive-mode comment in `crates/tn-reth/src/env/mod.rs` to cover the build path.

### F12. Info: scope
d30bb1809 was committed to the reviewed branch while the review ran. It has the same topic footer and is not in the scope file's list. It is covered by F3 and 2a. The image should be cut from a head whose commit list matches what was reviewed.

## Answers to the brief's questions

### 2a. Switch off = before
Yes, in behaviour.
- **Loop choice:** `run` picks the loop once (`lib.rs:381-387`). The body of `run_sequential` (`lib.rs:391-503`) is byte-identical to the base `run` body. I diffed the 112 lines.
- **The split:** with the switch off, `execute_consensus_output_with_signers` (`payload_builder.rs:86-112`) is `build_output` on a fresh scope, then `commit_output(.., ZERO, false)`, then the rollback on a `Persist` failure. The side effects stay in the base's order:
  - the empty-output info line, metric and span record, then the engine update and the same `ChannelClosed` error (now at :497-509, on the same thread at the same point);
  - on a persist failure, the same error line, metric and rollback, in that order, with the same error conversion;
  - the same announce and finalize errors;
  - an `output executed` line with exactly the old fields; `test_engine_lines_carry_consensus_ids` pins them.
- **The overlay:** an overlay with no anchor opens a fresh read transaction per root, as before (`output_overlay.rs`, `root_with_updates`).

Lines that run with the switch off and did not run before:
- `execution.rs:503-505`, and at d30bb1809 `env/mod.rs:274`: `persist_delay()`. It is the constant `None` without `tn-types/test-utils`; with that feature it reads an environment variable (F3).
- In `tn-reth/test-utils` builds only: the `PersistHolds` mutex and atomics (`execution.rs:284-290`, :495-496).
- Arc clones (`args.reth_env`, `built.blocks`, `engine_update_tx`).
- The output's span is exited after the build and entered again for the commit and the rollback.
- Five new metric series, registered and exported at 0 (D55).

None of these changes block contents, update contents or update order.

### 2b. Mixed fleet
No fork, no wrongful rejection and no stall.
- **What another validator checks:**
  - a header's `latest_execution_block`: the proposer's `recent_blocks` tip (`proposer.rs:1936`), checked by voters at `handler.rs:1290-1318` against their ring and then their canonical DB;
  - the epoch record's `final_state`: the ring tip.
- **What the switch cannot change:** blocks, roots and receipts are identical in both modes (I3, I10; F4 is local only), and batches do not depend on the switch.
- **What the switch does change:** only the timing of announces. A pipelined node announces N when N commits, earlier than a sequential node would.
- **Effect under load:** under persist-bound load, a pipelined proposer's header can name a block that a sequential voter reaches more than `VOTE_EXECUTION_WAIT` later. That wait is 1 s (`crates/config/src/consensus.rs:459`), against a bench-5 persist of about 1.2 s. The voter then refuses with the recoverable `ExecutionBehind`, and the requester asks again. During the roll, pipelined headers certify at the pace of the slower half.
- **Not a new class:** this is the existing behaviour of a validator with a faster disk.
- **e2e evidence:** the 2-on/2-off fleet passed 3 of 3, with two epoch boundaries under load and one restart of each kind.

### 2c. Liveness
Nothing that used to make progress is dropped or delayed without bound.
- A parked output is dispatched at T4 (`persister.rs:962-964`).
- The barrier clears on commit (:956-958) or on a post-commit failure (:981-983).
- `next_event` stays pending only when both slots are empty (:270-272), and the loop's `else` arm fails closed and cannot be reached (`lib.rs:598-602`).
- Shutdown and a closed stream drain the queue and both slots (`lib.rs:552-564`).
- A closed engine-update channel makes `blocking_send` return an error; it does not hang.
- The persist retry is unchanged (3 attempts, 100 ms apart), with N+1 parked meanwhile.
- An empty output's update now waits behind at most one commit in flight; that is by design (I2).
- The new halts are only the duplicate-number refusal (F8) and a dead commit task (F1), both fail-closed.

### 2d. Byzantine or slow peers
A peer's input reaches the engine only as certified consensus outputs, and the queue bound is unchanged (`MAX_QUEUED_OUTPUTS` = 8). The added cost is bounded:
- the executed blocks of one more output, and the recovered transactions of up to `MAX_QUEUED_OUTPUTS + 2` outputs (`lib.rs:65-69`);
- one repeat of N's overlay merges per seeded build (`persister.rs:775-778`), bounded by batch gas;
- one pinned read transaction that overlaps exactly one write, so the freelist does not grow beyond the sequential path.

Other effects:
- A leader whose output fails to build deterministically, such as `UnknownAuthority` on an empty closing output, halts every node in both modes. With the switch on, the previous output still commits first (T5).
- A Byzantine leader can influence only whether a build is seeded, which changes nothing consensus-visible (F4).
- A slow peer only adds the vote timing of 2b when it runs the other switch value.

### 2e. Restart and epoch boundary
The pipeline holds all of its state in memory:
- the in-memory and durable tips;
- the building, parked and committing slots;
- the `carry` with its pinned read transaction;
- the list of unpersisted blocks;
- the slot table, including `last_started` and `barrier`;
- the loop's bookkeeping.

On a restart all of it is gone, and `PersistPipeline::new` starts from `lookup_head()`. That reads reth's Finish checkpoint (`node_config.rs:364`), the same value the pin checks its anchor against. Everything converges:
- The blocks, the finalized and safe markers, and the Finish checkpoint commit in one transaction (`save_blocks`, `vendor/.../database/provider.rs:650`; markers at `execution.rs:529-531`).
- The ring is seeded from the DB (`node.rs:1865`), and the replay runs from the consensus pack.
- Because nothing above the DB was ever announced, every crash row C0-C5 and E1-E4 converges.
- The pinned transaction dies with the process.
- e2e evidence: the SIGKILL test, five kills × 3 runs, with two kills per run landing with two outputs in flight.

The pipeline lives as long as the node. At an epoch close it is idle, with tip == durable == the closing block C (barrier plus forwarder). `last_started` carries across epochs, and consensus numbers are global. On a graceful shutdown the loop drains. If the node aborts the engine future first, the blocking tasks finish their current call, and the state on disk is one of rows C1-C5.

### 2f. Determinism
The only input that depends on timing is whether a build is seeded (`persister.rs:165`, :858-860).
- It gives the same blocks, roots and written rows.
- Only the local `TrieUpdates` may differ in form (F4).
- The commit-first bias of `wait_slots` (:797-801) changes only the order of events.
- Engine updates leave in FIFO order through one commit slot.
- Reward-accounting increments run in build order, which is consensus order.
- `Instant` feeds only metrics and logs.
- The new code adds no map iteration and no wall-clock or random input on any consensus path.

### 2g. The scope's questions
1. **I3: one pinned snapshot per output.** No read during N+1's build sees N half-applied or a later snapshot.
   - **Roots** read the transaction pinned at dispatch, while the commit slot is empty (`persister.rs:444-459`). Its anchor is checked against `durable` (:450). The anchor is the Finish checkpoint, which advances inside `save_blocks`' transaction (`provider.rs:650`).
   - **EVM and `BLOCKHASH` reads** go through `ConsistentProvider`, which takes the in-memory head before it opens its DB transaction (`consistent.rs:77-78`). MDBX commits are atomic.
   - **Static files:** N's appends land before its MDBX commit. N's blocks stay in the head snapshot until `finalize_block` removes them, after the commit, so a build never resolves N from static files that are ahead of the DB.
   - **Tests:** `test_pinned_anchor_root_ignores_later_commit`, the trie digest in the proptest, and `test_finalize_during_next_build_keeps_unpersisted_blocks`, which uses the deterministic rendezvous hook.
2. **Durability before visibility.** Nothing consensus, a peer or the epoch record reads is ahead of the DB.
   - The engine update is sent after the persist (`payload_builder.rs:521` then :538). Empty outputs also go through the commit slot.
   - The ring is fed only by those updates (`node.rs:1912-1923`).
   - "Executed" in the backlog is set only on `Committed` (`lib.rs:733`).
   - The finalized and safe watches, and the canon notification, come after the commit.
   - `final_state` is the ring tip.
   - `canonical_tip()` at the close (`run_epoch.rs:958`, after the wait at :911) and at epoch entry (`start_epoch.rs:229`) sees a durable C.
   - Ahead of the DB: only the in-memory head and RPC (D53) and the local gas accumulator (I8). F1 is the reverse case.
3. **Crash matrix.** Every SIGKILL point between the start of N+1's build and the end of N's commit leaves the DB at the last committed output. Restart replays to the same chain (2e).
   - **A persist error that is not a crash (T6):** the pipeline waits for N+1's build. It then rolls N and N+1 back to `durable` in one call (`persister.rs:517-563`), clears `tip`, `built`, `carry` and `unpersisted`, and returns the error. The engine stops. The DB stays at N-1, and static files that ran ahead are healed at restart.
   - **Tests:** `test_persist_failure_rolls_back_both_outputs`, `test_late_persist_failure_rolls_back_both_outputs`, `test_persist_fault_while_next_output_builds`, and `prop_persist_fault_leaves_durable_prefix` (400 of 400 in the hunt).
   - **Exceptions:** F1 and F7, in memory only, with the node halting.
4. **Epoch close.** The next epoch's first output builds on a durable closing block, and no state from the wrong epoch is used.
   - The barrier is set when C is built (`persister.rs:898-900`), checked in `can_start` (:849) and cleared when C commits (:956-958).
   - `close_epoch` waits for C's update (`run_epoch.rs:911`), which is sent after C's commit. `adjust_base_fees` (:914) and `gas_accumulator.clear()` (:916) then run with nothing built past C.
   - The next epoch's first output is forwarded only after the new epoch starts, so it builds unseeded on a durable C.
   - **Tests:** `test_close_epoch_output_is_a_barrier` (gate 3), and the e2e epoch close under load (barrier holds 0 on every node).
5. **Two threads mutating reth's in-memory chain.** No data race, and no order in which the commit removes blocks the build still needs.
   - `update_blocks` and `remove_persisted_blocks` both take the `numbers` lock, then the `blocks` lock (`in_memory.rs:275-276`, :337-338).
   - The removal keeps and relinks every block above the persisted height (:347-366), and returns early if the persisted hash is gone (:329-332).
   - The commit thread never sets the canonical head.
   - The build resolves N through head-first snapshots, whose `Arc`s keep N's state alive, or through the DB, which already holds N when the removal runs.
   - The pipeline's rollback runs only with both slots idle. A failed build's own rollback can overlap `finalize_block(N)`, and both orders end with no blocks above N and the head at N (F9).

## Invariants and their tests
Each of I1-I11 has at least one test. The untested parts:
- **The I/O-side halves of I1, I3, I6 and I11:** the pinned-snapshot height refusal, the `take_seed` checks, the pin-failure fallback, the dead-commit-task path and the refused-start drain (F2).
- **Crash row C2 (a kill inside `save_blocks`):** reached in-process by the late fault plus the reopen in the proptest. No SIGKILL lands at that exact point; the e2e kills land at points read from the node's log.
- **Not run with the switch on:** the slow-executor e2e case, and the repository's own restarts, epochs and sigkill sets (ST-U12b notes).

## Known residuals
D45 is understated (F5). D52, D53, D54, D55, D56, the effects in design §7.1 and the listed test-coverage gaps are not re-reported: nothing found makes them worse than stated.

## What I did not examine
- I ran no `cargo`, and no test or bench. Gate 5, the cycle bench, is still open.
- I read tests only as evidence.
- Taken as given, not traced:
  - reth's startup static-file consistency check (#1238);
  - libmdbx's read-transaction timeout mechanism (D45);
  - the vendored reth code beyond the functions cited.
- Other bench-6 topics, except where this topic calls them or is called by them: the voter, proposer and epoch paths named above.
