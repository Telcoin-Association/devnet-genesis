# Review: sealed-keep (bench 6, issue #1807)

Commits, in branch order: `1169532a8` feat(config): add the sealed_tx_keep switch; `a00fae8bb` feat(batch-builder): hand the
switch to the batch builder and the pool side; `7cfe52acd` fix(batch-builder): start the batch builder on its reth env's
sealed_tx_keep; `edc616c0d` feat(reth): keep sealed transactions pooled and marked until their batch executes; `c08d78c33`
feat(batch-builder): keep sealed transactions pooled until their batch executes; `3bbcbe226` fix(node): clear sealed marks of
orphaned batches on every worker pool; `3ee6b629f` feat(node): tell the batch builder whether its worker seals through a
quorum; `fe86f1658` and `ae62cc47a` (e2e). Branch `bench/bench6-2026-11`.

The scope was written at `ae62cc47a`. The branch has since moved to `d91d65d3e`, but no production file of this topic changed
after `ae62cc47a`. Only `crates/config/src/node.rs` (mdbx-advice doc text; the switch field is now at 372) and the e2e file
(`341b2a269`, `d91d65d3e`, other units' work) moved. Line numbers below are at `d91d65d3e`. `reth/...` means
`vendor/reth/crates/transaction-pool/src/...`.

How this was produced:
- The repository's code review (`tn-review`) and security evaluation (`tn-security-eval`) ran on the seven production commits
  and, lightly, the two e2e commits. The diff was the commit list, not `main...HEAD`.
- For the security evaluation, these evaluators ran: consensus safety, state transitions (scoped to the pool's and builder's
  in-memory state and the orphan path), DoS, determinism, nemesis, DREAD and STRIDE. Contract safety, crypto correctness
  and dependency audit were not started: the diff has no Solidity, no cryptographic code and no `Cargo.toml`/`Cargo.lock`
  change.
- Both skills' verification ran inline, without sub-agents, so the verifiers saw each claim before checking it. To make up for
  that:
  - I read the whole production diff and its call sites myself before either skill reported, and wrote my own hypotheses down
    without passing them on.
  - Three of the findings below were reached independently by more than one source: L1 by me and both skills, L2 by both
    skills, and L3 by me and the security evaluation.
  - M1 is the one Medium whose mechanism I had not traced. One blind verifier, given only a neutral question and the code,
    found it POSSIBLE with the same interleaving.
  - M2's code facts were found by both skills and checked by me.
- No `cargo` was run and nothing was built. Frequencies are estimates from code and from the ST-B logs' summary lines.

## Verdict: APPROVE WITH FOLLOW-UPS

There is no Critical or High finding. The topic is consensus-safe:
- The switch changes nothing another validator checks, so a mixed fleet cannot reject each other, fork or stall.
- No transaction can execute twice. The EVM nonce rule allows one execution, and every extra copy the new code can produce is
  skipped identically on every node.
- With the switch off, every path is the previous behaviour. The new always-on work is bookkeeping that cannot change a
  decision (2a).
- The central claim holds. With the switch on, a transaction stays known to the node from submission to execution, and the
  ticket closes the late-mark race for every ordering of ack, canonical update and mark. The one exception is a timing-only
  path at the epoch's orphan pass (L1).

The two Medium findings are about reading the benchmark, not about node correctness:
- **M1:** a build that overlaps a canonical update can re-pack this node's own just-executed transactions. That puts
  `nonce too low` skips on the switch-on arm, a number the acceptance list says should be about 0.
- **M2:** with the switch on, about 9,600 in-flight transactions per node at M16 sit in reth's 10,000-transaction pending
  sub-pool. The devnet passes no txpool flag, so crossing the cap silently drops accepted transactions, which looks like
  #1807 itself.

Nothing must change before the benchmark image. Recommended, in order:
1. Before run 1 (operator, no code): give the pending sub-pool headroom on both arms, or at least record each node's pending
   count and the pool's eviction counters at every blast (M2).
2. If a build slot is free: take M1's gated fix (a few lines, switch-off byte-identical) and L1's fence (about 5 lines) into
   the image. If M1 is not taken, the run-1 analysis must not read switch-on `nonce_too_low` skips as client duplicates.
3. Before the upstream PR: M1, L1-L4 and the doc corrections.

## Findings

### M1. Medium (benchmark reading), Low (security), CONFIRMED. A build that overlaps a canonical update re-packs this node's own just-executed transactions

Found by three security evaluators (determinism, state transitions, nemesis) and confirmed by a blind verifier.

Where:
- `crates/batch-builder/src/batch.rs:144` and `:175-178`.
- reth's iterator is a snapshot: `reth/pool/mod.rs:999-1001` (the read guard is dropped when the iterator is returned),
  `reth/pool/pending.rs:108-117` (`best()` clones `by_id` and the independent set) and `reth/pool/best.rs:86-88`, `:161-165`.
  The copy sees additions through its receiver and never sees removals.
- The maintenance update prunes first, at `crates/tn-reth/src/txn_pool.rs:939`, and then unmarks at `:946-949` /
  `sealed_txs.rs:196-221`.
- `crates/batch-builder/src/lib.rs:742-748`: after a `Kept` outcome the next build starts at once.

Sequence:
1. Batch B1 (digest D1) holds T. It reaches quorum, `keep_sealed` marks T (`lib.rs:480` → `txn_pool.rs:1079` →
   `sealed_txs.rs:170-188`), and the run loop starts build B2.
2. B2 takes its snapshot (`batch.rs:144`). T is in it, pooled and marked.
3. B1 executes. The pool's maintenance task runs on another blocking thread and prunes T (`txn_pool.rs:939`). T is still
   marked.
4. `clear_executed` unmarks D1 (`txn_pool.rs:946`), so `is_sealed(T)` is now false.
5. B2's walk reaches T in its stale copy, reads `is_sealed` = false (`batch.rs:175`) and packs T (`batch.rs:240-247`).
6. B2 reaches quorum. `mark_sealed` marks only what the pool holds (`txn_pool.rs:1079`, `:1112-1114`), so T is not marked: no
   stale mark is left.
7. B2 executes and every node skips T as `nonce too low`.

The same path opens through the eviction sweep (`sealed_txs.rs:264`): a marked T evicted after the snapshot loses its mark and
can be re-packed.

Effect:
- No loss, no double execution, no stuck mark.
- The cost is T's gas and bytes in B2, one more broadcast and vote, and one `nonce too low` skip on every node.
- If B2 happens to equal the earlier set, the same digest executes twice.
- With the switch off this cannot happen for the node's own transactions: the run loop awaits the prune
  (`lib.rs:792-797`) before it can start the next build. The same snapshot staleness exists in both modes for copies mined
  from peers' batches.

Frequency:
- It needs the prune and the clear of one update to land between B2's snapshot and the walk reaching T.
- The walk follows priority, then submission order (`best.rs:161`). Older marked transactions come first, which shrinks the
  window.
- The walk never breaks early and includes every marked in-flight transaction (about 9,600 at M16), which widens the window.
  So does OS preemption on loaded VMs.
- Local evidence: the three switch-on S9 runs (1,742-2,928 transactions each) show `nonce_too_low` = 0 on all four nodes
  before and after the kill (`/home/drtnarg/coding/telcoin/tn-b6-u2/target/tmp/st-b-{all-run1,pass2,pass3}.log`). It is rare at
  four-node scale.
- The keep-fleet e2e prints `nonce_too_low` but does not assert it.

Why it matters:
- I-2's acceptance list for the fixed build says "`nonce too low` skips ≈ 0" (`sealed-keep-test-cases.md:119`).
- In the switch-on arm, this race and the other sources of extra copies (lag clears, evictions, fee bumps) cannot be told
  apart from the logs.
- The doc claims at `txn_pool.rs:903-904` and `sealed_txs.rs:194-195` ("the builder never sees a mined transaction as
  unmarked and still pooled") hold for the live pool, not for the builder's copy.

Fix:
- With `keeps_sealed`, skip a candidate the pool no longer holds. Read the mark first, then the pool's presence.
- Either do it per candidate (pass the flag in `BatchBuilderArgs`; this keeps the batch's gas, bytes and nonce accounting
  consistent) or filter the selected hashes once through `held()` after the walk.
- It holds for every interleaving. Maintenance prunes (`:939`) before it unmarks (`:946`), and the sweep unmarks only
  hashes the pool no longer holds. So a candidate seen unmarked because of either path had already left the pool, and the
  later presence read finds it absent.
- Do not put the presence check inside `WorkerTxPool::is_sealed` as the blind verifier suggested. That would also run with
  the switch off and change what switch-off selection skips.
- Correct the two doc comments.

When: recommended before the benchmark image (small, gated). Required before the upstream PR.

### M2. Medium (benchmark confound), Low (security). Mechanism CONFIRMED; the trigger needs a node's pending sub-pool above 10,000. Sealed in-flight transactions sit in reth's pending cap, and truncation silently drops other accepted transactions

Found by six security evaluators. The code review classed it as the accepted residual. I side with the security evaluation:
it is worse than stated, for the reasons below.

Where:
- TN seeds only `max_account_slots` = 256 (`crates/tn-reth/src/cli.rs:148`, `:172-189`). The pool reads reth's defaults
  (`txn_pool.rs:332`): 10,000 transactions and 20 MB per sub-pool (`reth/config.rs:15`, `:18`).
- Above the cap, `remove_to_limit` (`reth/pool/pending.rs:389-470`) drops each worst sender's highest nonce first, and the
  victims' descendants go with them (`reth/pool/txpool.rs:1258-1276`).
- Only the transaction being inserted is told it was discarded (`reth/pool/mod.rs:686-716`). Earlier accepted ones vanish
  silently.
- The devnet passes no `--txpool…` flag anywhere in `devnet-genesis` (grep), so the default applies on the fleet.

How it is worse than the residual: U6a and `bench6-g1-notes.md:349` state the per-sender 256 slots and that "the queued and
pending gauges will read higher", and conclude the bench windows (16 and 4) are clear. That covers a per-sender refusal, which
the client sees. It misses the global cap:
- At M16 (600 × 16, `bench6-contract.md:122`) about 9,600 transactions per node are in flight.
- With the switch on nearly all of them are pending at once. With it off, the sealed share is out of the pool. So the
  switch-on arm runs at about 96 % of the cap.

Sequence:
1. M16 load on validator X with the switch on: about 9,600 pending, sealed and unsealed.
2. Anything more pending on X, such as a second client, a blast overlap or a recovery burst, crosses 10,000.
3. reth truncates the newest (usually unsealed) tail nonces of the worst senders, plus their descendants, after their
   clients were told `Ok`.
4. X has no record of them. The senders stall until the 300-s resend: #1807's symptom by another path, on the switch-on
   arm only.

Fix:
- Before run 1 (operator): set `--txpool.pending-max-count` and the size cap with headroom (2-3 × peak per-node in-flight),
  identically on both arms. Or at minimum record per-node pending and the pool's eviction counters at every blast, so a
  crossing is visible.
- Upstream: seed a TN pending default in `init_reth_defaults`, or state the global cap in the residual.

### L1. Low, PLAUSIBLE (timing only). A mark that lands after the next epoch's orphan pass is never cleared

Found independently by my own read, by the code review and by five security evaluators. The DREAD evaluator doubted a live
path exists.

Where:
- `sealed_txs.rs:240-244`: `clear_orphaned` only unmarks. It records nothing and raises no floor, so `mark_present`
  (`:178`) still accepts an older ticket.
- `txn_pool.rs:1071-1082`: the mark runs in a raw `spawn_blocking` that the task manager does not track.
- `lib.rs:479-481`; `run_epoch.rs:613-645` (shutdown notice, 200 ms grace, abort, join) and `:411`; `close_epoch.rs:200`,
  `:258-262`.

Sequence:
1. In epoch N the worker acks digest D `Ok` during the shutdown grace, and `keep_sealed` queues the mark closure.
2. The epoch's tasks are aborted. Dropping the JoinHandle does not stop the blocking closure.
3. The closure is delayed past epoch N+1's `orphan_batches`, which clears D's marks, re-pools D's transactions and removes
   D's cache row.
4. The closure runs. D never executed, so the ticket passes, and D's still-pooled transactions are marked under a digest
   that will never execute and has no cache row.
5. Nothing clears the mark:
   - not an execution;
   - not an orphan pass;
   - not the sweep (the transactions stay pooled);
   - not a resend (it answers `AlreadyImported`).
   Only a lag event, a restart, or a peer mining the same hash ends it.

Effect: the sender is stuck on that node, and its later nonces fall into L2's churn with no end.

Likelihood: the closure must wait through the whole epoch close and the next epoch's startup, hundreds of milliseconds at
least. On a mid-epoch re-entry (`RunEpochMode::ModeChange`, `run_epoch.rs:64-77`) the window is shorter, but there the digest
may still commit and clear.

Fix: about 5 lines and a test. Fence every pool in `orphan_batches` before the clear loop. Either:
- bump `generation` and `remember_executed(digest)` inside `clear_orphaned`, which refuses only stale tickets for that digest;
  or
- raise the floor as a lag does, which refuses every pre-pass ticket and is safe because no builder of the new epoch exists
  yet.

It is harmless with the switch off.

When: before the upstream PR. It is cheap enough for the image.

### L2. Low, CONFIRMED. While an earlier nonce sits marked in a late own batch, the sender's later nonces are re-sealed and skipped every commit cycle

Found by the code review and three security evaluators. The unit tests pin the immediate re-seal: `txn_pool.rs:2466-2470` and
`lib.rs:2902-2907`.

Where: `sealed_txs.rs:204-210`, `:382-388` (an executed digest's leftovers are unmarked with no check for a lower nonce of
the same sender still marked); `batch.rs:175-178` (the skip keeps later nonces buildable; reth unlocks n+1 on yield).

Sequence:
1. D1 = {a0..a7} and E = {a8..a15} are both sealed and marked.
2. E executes first. a8..a15 are skipped as `nonce too high`, and E's update unmarks them.
3. The builder re-seals them at once as E′.
4. If E′ executes before D1, it is skipped and re-sealed again. This repeats until D1 executes, the epoch's orphan pass runs,
   or a lag event occurs.

Cost:
- Up to window − 1 transactions (15 at M16) per affected sender per cycle, sealed, certified and executed as `nonce too high`
  skips. Nothing is lost.
- In D51's case (D1's header never certifies) the loop lasts the epoch.

This is not D51: D51 says the stuck batch holds its own marks, not that its sender's later nonces churn.

Fix: a decision.
- (a) Accept it, widen D51's text, and add a counter for "unmarked while a lower nonce of its sender is still marked", so the
  bench can see it.
- (b) Re-home the leftovers under the digest of the sender's lowest still-marked nonce.

When: before the upstream PR. For bench 6, read switch-on `nonce too high` skips on slow-commit nodes as this churn, not as
loss.

### L3. Low, CONFIRMED. While anything is marked, every builder wake walks the whole pending set

Where:
- `lib.rs:667-700`: the build gate is `pending > 0`, and marked transactions count as pending.
- `lib.rs:750-756`: `AllSealed` clears `failed_hold`.
- `lib.rs:813-816` (the tick) and `:828-844` (any admission arms the 40 ms fill delay).
- `txn_pool.rs:858`: the admission listener fires for queued and parked admissions too.
- `batch.rs:144`, `:168-178`.

Effect:
- With only marked transactions pending, every `max_batch_delay` tick (250 ms on the devnet), every canonical update and every
  admission (even a nonce-gapped queued one) starts a build. Each build clones the pending set and takes the store mutex once
  per mark, then ends `AllSealed`.
- With the switch off the same state has `pending == 0` and builds nothing.
- Estimated 3-6 ms per walk at 10k marks. There is no busy loop.
- `sealed_txs_skipped_total` grows by the marked count on every walk. The contract row says it "counts many times"; the
  G1 note's "one build after every kept batch" understates it.

Fix: an `AllSealed` hold that only a pending-subpool admission or a canonical wake lifts; optionally snapshot the marks once
per build.

When: before the upstream PR.

### L4. Low (latent), CONFIRMED. Clearing a mark is a side effect of the generic re-pool method

Where: `txn_pool.rs:1002-1010`: `clear_repooled` runs before every add, whatever the caller. Callers:
- the orphan re-pool (`close_epoch.rs:157`), already covered by `clear_orphaned` at `:258-262`;
- the forwarder requeue (`txn_pool.rs:611`);
- `submit_txn_if_mine` (`crates/batch-validator/src/validator.rs:147-164`), which has no production caller today.

Effect today: the forwarder requeue can clear a live mark at most once per tracked forward. `forward_pending.rs:298-313`
returns the entry to `Queued`, and a validator never re-forwards it. It happens only on a node that was forwarding and now
seals by quorum, and costs one duplicate copy.

If a gossip path is ever wired to this method, any committee peer could clear marks and force re-seals.

Fix: drop the clear from `add_recovered_transaction_external` (`:1007`), since the orphan path already clears every orphan
digest. Update `sealed_txs.rs:23-25`, `txn_pool.rs:996-1001` and the test near `:2479-2497`.

When: before the upstream PR.

### Info

- **I1. Store mutex across reth's lock.** The store's `std::sync::Mutex` is held across reth's read lock in `mark_present`
  and `drop_missing` (`sealed_txs.rs:177-185`, `:264-270` via `txn_pool.rs:1112-1114`). There is no deadlock:
  - The order is store, then pool, everywhere, and reth never calls into the store.
  - Selection holds no reth lock (`reth/pool/mod.rs:999-1001`).

  Async callers can block a tokio worker for one reth write section, which is milliseconds: `seal_ticket` (`lib.rs:449`),
  `sweep_due` (`txn_pool.rs:1097`), `clear_repooled` (`:1007`), `clear_all_lag` (`:668`), `clear_orphaned`
  (`close_epoch.rs:260`). Optional fix: an atomic generation, and the sweep's lookup done outside the lock.
- **I2. Executed-digest memory.** The memory holds 4,096 digests (`sealed_txs.rs:57`, `:392-408`). A forgotten digest would
  accept a late mark, which needs more than 4,096 executions while the builder task is unpolled: not credible. Hardening: a
  forgotten-through watermark.
- **I3. JoinError fallback.** On a `JoinError` (`lib.rs:873-900`) the batch falls back to `Mined`, and the optimistic nonce
  advance (`lib.rs:792-797`) makes reth discard the same senders' other marked in-flight transactions. They still execute
  from their batches but lose visibility. That is broader than the docs' "this one batch". It is reachable only on a panic or
  at shutdown. Fix: return `Kept` with no marks, or prune without `changed_accounts`.
- **I4. Scale of a lag clear.** A lag clear makes the whole in-flight set re-sealable at once (up to about 9,600 at M16) on a
  node already behind. It is within the accepted per-transaction residual. The doc at `sealed_txs.rs:285-286` describes only
  the refused tickets.
- **I5. Interplay with `digest_dedupe` (cross-topic).** An identical re-seal acked `Ok` without reaching consensus can be
  marked under a digest that already executed. It is held until the epoch's orphan pass: delayed, not lost.
- **I6. One-tick repair delay.** The S1 repair can wait one `max_batch_delay` tick, when the builder's canonical wake
  (`lib.rs:710-715`) runs before maintenance's clear (`txn_pool.rs:946`).
- **I7. Wrong or misleading text.**
  - The `lib.rs:321` comment says the env builds the pools from the switch. The pools never read it
    (`sealed_txs.rs:39-42`).
  - `close_epoch.rs:157-159` logs "pool refused an orphaned transaction" at debug for every still-pooled orphan
    (`AlreadyImported`) when the switch is on.
  - The two doc claims in M1.
- **I8. Wasted state read.** `changed_accounts` and `get_account_balances` (`batch.rs:318-331`) still run on every switch-on
  build, though only the `JoinError` fallback uses them: one state-provider read per build.
- **I9. Audit gaps.**
  - The orphan-clear count is discarded (`close_epoch.rs:260`).
  - A mark moving between digests is silent.
  - There is no mark-age gauge, so a stuck mark (L1) shows only as `tn_reth_sealed_txs_marked` not returning to 0.
- **I10. Gaps in the e2e evidence.**
  - Since `ae62cc47a`, an S9 kill that leaves nothing to resend is reported instead of failing. Two of the three S9 runs had 0
    unexecuted at the restart; one reproduced the case (32 accepted as new, each landed once).
  - The keep-fleet check does not assert `nonce_too_low`.
  - The live S1 repair was never exercised: no `nonce too high` skip occurred in the switch-on runs.
  - S6 and S7 are not written.

## Answers to the brief's questions

### 2a. Switch off = before
Yes. These lines now run with the switch off; none can change a decision:
- `SealedTxs::new` and `register_series` (`txn_pool.rs:401`; `sealed_txs.rs:420-425`): six series at 0, and the per-worker
  skip counter (`metrics.rs`).
- `clear_executed` on every canonical update (`txn_pool.rs:946-949`). It bumps the generation and records each block's
  `ommers_hash` in a memory capped at 4,096 per pool (`sealed_txs.rs:390-403`), under 1 MB. The mined-hash pass is skipped
  while nothing is marked (`:213`).
- `sweep_sealed_marks` once per maintenance-loop iteration (`txn_pool.rs:558`, `:1096-1110`). It is a lock and an
  empty-map check.
- `clear_all_lag` on a lag (`txn_pool.rs:668`). It raises the floor over empty maps and logs nothing.
- `clear_repooled` on every re-pool (`txn_pool.rs:1007`): a miss.
- `is_sealed` per selection candidate (`batch.rs:175`): one uncontended mutex, always false.
- In the builder:
  - The skip counter gets +0 per build (`lib.rs:422`).
  - With `sealed_skipped` = 0 the outcome is `Empty` (`lib.rs:437-441`).
  - The ticket is `None`, so the outcome is `Mined` (`lib.rs:449`, `:479-481`).
- One info line `batch builder started` per builder per epoch (`lib.rs:642-650`), and a `sealed_skipped` field on an existing
  debug line.
- `clear_orphaned` for each orphan × pool (`close_epoch.rs:258-262`): a no-op.

The only production marking call is `keep_sealed`, reached only when `keeps_sealed() = sealed_tx_keep && seals_via_quorum`
(`lib.rs:363-365`, `:449`, `:479-480`). Both inputs default to false (`config/src/node.rs:372`, `env/mod.rs`,
`lib.rs:321-324`).

### 2b. Mixed fleet
Safe. The switch changes only which locally pooled transactions this node packs into its own batches, and what its RPC answers
(pending nonce, lookup by hash, `already known`). Nothing another validator checks depends on it:
- The batch validator is stateless (`crates/batch-validator/src/validator.rs:82-140`: size, decoding, type allowlist, gas,
  epoch, signatures). It does no nonce or duplicate check.
- Headers, votes and certificates carry only digests.
- Every committed batch executes as one block whose `ommers_hash` is its digest on every node
  (`crates/engine/src/payload_builder.rs:287-295`; `crates/tn-reth/src/evm/config.rs:249`).

The extra copies a switch-on node can seal (M1, L2, a lag clear) are skipped identically everywhere. ST-B's mixed fleet with a
restart of a switch-on node was one chain in 4 of 4 runs.

### 2c. Liveness under the switch
- **Transactions.**
  - Stuck forever only through L1 (timing).
  - Delayed but bounded:
    - D51, until the epoch's orphan pass;
    - L2's churn of later nonces, until the earlier batch executes;
    - I5, until the epoch's orphan pass;
    - an `AllSealed` park, at most one tick (`lib.rs:750-756`, `:813-816`).
  - Dropped: accepted unsealed transactions above the pending cap (M2).
- **Batches.** The next build waits for the mark, one `spawn_blocking`, milliseconds (`lib.rs:479-485`). A `JoinError` falls
  back to the switch-off prune (`lib.rs:873-900`).
- **Headers, votes, certificates:** untouched.
- **Epoch close.** The only new work is a synchronous O(orphans × pools) clear (`close_epoch.rs:258-262`). It cannot fail and
  runs before recovery and before any builder starts (`run_epoch.rs:411`, then `:413-429`).

### 2d. Byzantine or slow peers, and clients
- **A peer** can neither create nor keep our marks. It can only clear one correctly, by executing our batch or mining the
  same hash. Executing our digest early only gets a late mark refused.
- **A slow validator** pins only its own pool (M2) and churns its senders' later nonces (L2). The cost is at most window − 1
  wasted copies per affected sender per cycle, until its orphan pass.
- **A client:**
  - A resend of sealed bytes now answers `already known`, which is better than before.
  - Each fee bump of 10 % or more on a marked transaction gets one more copy sealed (D51). Only one pays. With the switch
    off, a resend of the same bytes did this for free.
  - A trickle of nonce-gapped queued transactions drives builder walks while marks exist (L3).
  - No pinning is cheaper than with the switch off: a marked transaction executes and pays, or is held only in D51's case.
  - #1158 is not worse: marked transactions stay in reth's cumulative-cost check, so the optimistic debit is not needed.
- **Bounds:**
  - CPU per build: O(M) for the clone, plus O(M) mutex operations for M marks.
  - The sweep: at most once a second, O(M) under one read lock.
  - Memory: at most the pool's own limits, plus 4,096 digests per pool.

### 2e. Restart and epoch boundary
- **Restart.** The marks, the generation and the executed-digest memory are in memory and lost, as is reth's pool. The orphan
  pass re-pools the cached rows unmarked (`close_epoch.rs:243-292`). If such a batch still commits, its copy is skipped
  (D64).
- **Epoch boundary.**
  - The store lives in the pool, which outlives the builder (`txn_pool.rs:245-247`).
  - Marks of committed batches clear when those batches execute.
  - Orphan digests are cleared on every pool before the new builders start.
  - Retired pools drop their marks (U6a).
  - The gap is L1.
- **Mid-epoch re-entry.** `run_epoch` is also re-entered for the same epoch without a restart (`ModeChange`,
  `run_epoch.rs:64-77`), and the orphan pass runs on every entry. There it unmarks current-epoch batches that peers may still
  commit, so one re-sealed copy may be skipped. That is the same exposure as with the switch off.

### 2f. Determinism
- Nothing consensus-visible reads the store.
- HashMap iteration (`sealed_txs.rs:184`, `:204-217`, `:269-274`, `:384`) touches only local maps and counters.
- `Instant` only rate-limits the sweep.
- Batch contents were already local and timing-dependent. M1 adds a timing dependence in what this node packs, but peers
  validate and execute the result identically.

### 2g. The scope's questions
1. **Exactly-once.** No sequence executes a transaction twice: the nonce rule allows one execution and every copy is skipped.
   For "never executes", the cases:
   - Quorum ack, then the batch never certifies: held until the orphan pass (D51), then cleared and re-pooled.
   - Header cancelled and its digests re-queued: the digest is proposed again, executes and clears.
   - Orphaned at an epoch close: cleared on every pool, then re-pooled.
   - Restart: D64.
   - The mark task fails: the prune fallback, which is broader than stated (I3).
   - Evicted while marked: the sweep drops the mark within about 1 s, and the transaction executes from its batch.
   - Fee bump: D51.

   Stuck marked forever: only L1 (timing) and, not credibly, I2.
2. **Seal ticket.** The race is closed for every ordering. Write E for the execution, R for the pool update, C for
   `clear_executed` and M for the mark:
   - M before E: cleared by C.
   - E < M < R: cleared by R and C.
   - R < M < C: only the skipped transactions are marked, and C clears them under the store lock
     (`sealed_txs.rs:177-188` vs `:201-210`).
   - M after C: refused (`:178`, `:405-408`).
   - Maintenance behind the engine: the mark lands first and clears when the update is processed.
   - Lag: refused by the floor.

   Exceptions: L1 (no record at the orphan pass) and I2.

   If two batches hold one transaction, `insert` moves the mark to the newer digest (`:351-364`), and a mined hash clears it
   under any digest. Identical digests share marks: at worst extra copies, never a stuck mark.
3. **Pool accounting.** Yes:
   - Marked transactions count against the 256 per-sender slots (accepted residual) and against reth's 10,000 pending cap.
   - Above the cap, truncation silently drops other senders' accepted tail nonces and their descendants. This is worse than
     stated, and at M16 the margin is about 400 (M2).
   - A client cannot pin space beyond its own paying transactions' seal-to-execution time, except in D51's case.
4. **Nonce view.**
   - `eth_getTransactionCount(pending)` is the canonical nonce plus the run of consecutive pooled transactions
     (`txn_pool.rs:2336-2347` mirrors reth's RPC computation).
   - With the switch on it counts marked transactions throughout, including after an out-of-order skip, a lag clear or an
     orphan clear, because they stay pooled.
   - It falls back only if a marked transaction leaves the pool: an eviction, M2's truncation, the I3 fallback or a restart.
     Only then can a correct client reuse a nonce, and then one copy executes and the other is skipped.
   - With the switch off it falls back to the canonical nonce at every ack (pinned by the test at `txn_pool.rs:2397`). The
     switch strictly improves this.
5. **Recovery failing partway after the orphan clear.** It is safe:
   - A closed epoch's orphan cannot execute. Rows evicted at forward time executed, rows left were never forwarded, and an
     old-epoch batch fails the validator's epoch check.
   - Clearing a mark never removes a pool entry.
   - Retained rows are retried at the next pass (`close_epoch.rs:206-208`); those transactions answer `AlreadyImported`.
   - Builders do not start if `orphan_batches` fails (`run_epoch.rs:411`, `?`).
   - The worst case is a mid-epoch re-entry whose orphan still commits: one copy, skipped. That existed before this topic.

## Not examined
- No build, test run or measurement. M1's frequency and L3's cost are estimates. The ST-B logs were read only for their summary
  lines.
- reth's RPC `eth_getTransactionCount` code; the pool test helper was taken as its mirror. The executor's skip code was taken
  from its docs and the evaluators' reading.
- Proposer and subscriber internals that set how long L2 lasts, and `digest_dedupe` beyond its interplay with marks (I5).
- The bench fleet's actual traffic besides the generators, and the launch configuration beyond a grep for txpool flags (M2).
- Configurations with more than one worker. State-sync or snapshot paths that might execute blocks without a canonical
  notification to the pool; a mark under such a digest would not clear.
- The e2e changes after `ae62cc47a` (`341b2a269`, `d91d65d3e`), which belong to other units.
