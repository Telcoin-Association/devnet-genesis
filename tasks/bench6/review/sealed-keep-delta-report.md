# Review: sealed-keep delta (bench 6, issue #1807), the fixes for M1, M2 and L1

Commits, in branch order, on `bench/bench6-2026-11` at head `80a0c76c0`:
- `891e2b962` double the pending sub-pool limits of a pool that keeps sealed transactions
- `d2c695797` skip a candidate that left the pool after the selection's snapshot
- `cc022b4d0` refuse a sealed mark that lands after its digest was orphaned (superseded by `c8659e2fa`)
- `8b23bb608` hold back a sender's later nonces when a replacement took the candidate's nonce
- `c8659e2fa` fence late sealed marks at the orphan pass with the ticket floor
- `80a0c76c0` build the worker pool with the env's `sealed_tx_keep`

Line numbers are at `80a0c76c0`. `reth/...` means `vendor/reth/crates/transaction-pool/src/...`.

How this was produced:
- The diff was the six commits (`git show --format=`), not `main...HEAD`. Nothing was built, run or edited.
- The repository's code review (`tn-review`) ran in one sub-agent. Its verification step ran inline: it re-read each
  finding's lines before reporting.
- For the security evaluation, three evaluators ran as separate sub-agents: state transitions, DoS/resource bounds, and
  the logic audit (the nemesis method). Not started, because the delta has no consensus-message, cryptographic,
  Solidity or `Cargo.toml` change and feeds nothing consensus-visible: consensus safety, crypto correctness,
  determinism, contract safety, dependency audit, DREAD and STRIDE.
- Before any evaluator reported, I traced the verdict-bearing premises myself and wrote six hypotheses to the
  checkpoint. Each was later reached independently by at least one evaluator.
- After triage nothing is Medium or higher, so no blind verifiers were started. I re-read every finding below at its
  lines. Where a mechanism goes through reth, I read the reth code too.

## Verdict: APPROVE WITH FOLLOW-UPS

There is no Critical, High or Medium finding. Nothing must change before the benchmark image.

The three findings are closed:
- **M1 is closed.** With the switch on, this node never re-packs one of its own transactions after its batch executed,
  whatever the interleaving with a canonical update or the eviction sweep. The walk reads the mark, then presence; the
  maintenance task prunes, then unmarks (2g Q1).
- **M2 is closed in code.** A switched-on node's worker pools take twice the configured pending limits: 20,000
  transactions and 40 MiB at the devnet's defaults. The only production construction path carries the switch
  (`engine/inner.rs:170` → `env/mod.rs:555-564` → env from `node.rs:1813-1820`). That leaves about 10,400 slots above
  the roughly 9,600 in-flight transactions at M16.
- **L1 is closed.** The orphan pass raises the ticket floor, so every mark whose ticket predates the pass is refused.
  A digest that was acked `Ok` is, at the next pass, either an orphan (the pass runs and raises the floor) or already
  handed to the engine (it executes, and its mark is cleared or refused) (2g Q2).
- The prior report's I7 first bullet is now true: the env does build the pools from the switch.

With the switch off, every decision is as before (2a). A mixed fleet is safe (2b).

Four Low and six Info follow-ups, all for the upstream PR. The one item two evaluators rated Medium is the per-sender
slot cap. It is U6a's accepted residual, and the delta did not make it worse; it is under "Residuals re-checked".

## Findings

### L5. Low, CONFIRMED. The presence check takes reth's pool read lock for every unmarked candidate, including those after the batch is full

Found by the DoS evaluator and the logic audit.

Where:
- `crates/batch-builder/src/batch.rs:200` runs before the capacity arms at `:210-266`.
- The walk never stops early (`batch.rs:178-294`).
- `holds` is reth's `contains` under `pool.read()` (`txn_pool.rs:1270-1271`; `reth/pool/txpool.rs:1432-1434`).
- At the doubled cap, the snapshot clone (`reth/pool/pending.rs:108-117`) and the walk cover up to 20,000 entries.

Sequence:
1. Switch on. Pending is near the doubled cap.
2. The batch fills early. The walk still yields one candidate per remaining sender, and calls `holds` on each before
   the capacity arm marks the sender invalid.
3. reth's lock is a task-fair parking_lot RwLock, so each `holds` call parks behind any writer queued at that moment
   (an admission or a canonical update).

Effect: build time grows by the overlapping write sections, milliseconds at most. It is bounded and cannot stall: no
lock is held across calls, and none is nested with the store mutex. At bench steady state (about 9,600 marked) the
walk is the size it was before. Only above 10,000 pending does it double, from about 3-6 ms to 6-12 ms by L3's
linear estimate (not measured). Before this delta, those transactions were silently evicted.

Fix: do the presence check in the pack arm (`batch.rs:267`). Every other arm already skips the candidate or marks its
sender invalid, and removing a hash that is gone does nothing. Switch-gated as now.

When: before the upstream PR. For bench 6, watch `BuildStats.build` (`batch.rs:364`) on the switch-on arm.

### L6. Low, PLAUSIBLE (narrow race; mechanism traced). An evicted chain whose tail is resent mid-walk is packed across a nonce gap

Found by the logic audit. New in `d2c695797`.

Where: `batch.rs:200-205`. reth unlocks the next nonce before it yields a candidate (`reth/pool/best.rs:214-217`).
`holds` spans every sub-pool, queued included (`reth/pool/txpool.rs:1432-1434`). Truncation removes a victim's
descendants with it (`reth/pool/txpool.rs:1258-1276`).

Sequence:
1. The snapshot holds sender S at nonces n, n+1 and n+2, all unmarked.
2. During the walk, reth truncation evicts the whole chain.
3. S's client resends n+2 alone, same bytes. The pool takes it into queued because of the gap.
4. The walk reaches n. Neither the hash nor the nonce is held, so it is a plain skip, and n+1 is already unlocked.
   n+1 is skipped the same way, which unlocks n+2. n+2 is held, so it is packed.
5. Every node skips n+2 as `nonce too high`. With the switch on it is then marked; the execution unmarks it, and it
   waits in queued.

Effect: one wasted copy. Nothing is lost that the eviction had not already dropped. Before the delta, the stale
snapshot packed the whole chain. Step 3 needs a resend of only the tail, inside one walk, so it is rare.

Fix: in the branch where neither the hash nor the nonce is held, plain-skip only if the nonce has executed (the
sender's state nonce is above n); otherwise call `replaced_since_snapshot`. Switch-gated.

When: before the upstream PR.

### L7. Low, CONFIRMED. A selection whose only skips are "not held" or a hold-back parks the builder for up to one tick

Found by the logic audit and the state-transitions evaluator.

Where: `batch.rs:200-205` counts nothing. The outcome is chosen at `lib.rs:437-441` (`AllSealed` only if
`sealed_skipped > 0`). `Empty` sets `failed_hold` (`lib.rs:764-766`), and while it is set an arrival does not arm the
40 ms fill delay (`lib.rs:836-843`). Arrivals during a build are drained at `lib.rs:727`, and the tick clears the hold
(`lib.rs:813-816`).

Sequences:
- (a) The builder wakes on a canonical update (`lib.rs:710`) before the maintenance task applies it. Every pending
  candidate is one of the batch's just-executed transactions, read as unmarked and not held. The batch is empty with
  `sealed_skipped = 0`, so the outcome is `Empty`. The next build waits for the next canonical update or tick, not an
  arrival's 40 ms.
- (b) The replacement R is held back in a build where everything else was sealed, so the outcome is `AllSealed`. R's
  arrival was drained at `:727`, so R waits for the next wake.

Effect: at most one `max_batch_delay` tick (250 ms on the devnet) or one canonical update, and only when nothing else
is buildable, that is at low load. Not a bench-6 concern: the bench generator does not fee-bump.

Fix: count presence skips, and hold-backs, toward the `AllSealed` decision (a counter of their own also gives the bench
the visibility the DoS evaluator asked for, I15). Rebuild at once after a hold-back.

When: before the upstream PR.

### L8. Low, CONFIRMED. The orphan fence depends on the own-batch cache's lifecycle and lives inside a per-digest function

Found by the state-transitions evaluator and the code review, and matches my own trace.

Where:
- `close_epoch.rs:246`: the fence runs only when the orphan list is non-empty.
- `close_epoch.rs:259-263`.
- `sealed_txs.rs:250-258`: `clear_orphaned(digest)` raises the floor for the whole store.

It is safe today:
- The worker writes the `OurNodeBatchesCache` row before the quorum attest (`consensus/worker/src/worker.rs:416`).
- It removes the row only on a quorum failure, which means no ack and no mark (`:451`, `:474`), or at the hand-off to
  the engine (`run_epoch.rs:791`, `:1420-1427`). After the hand-off the batch executes, and `clear_executed` clears its
  mark or `executed_after` refuses it.
- The only caller runs before any builder of the new run starts (`run_epoch.rs:411` vs `:413-429`).

Residual: a run that ends with no orphans, whose last digest executes and is then pushed out of the 4,096-entry
executed memory before its untracked mark lands. That is the prior report's I2, not credible.

Future risk: a caller of `clear_orphaned` in the middle of a run would refuse that run's in-flight mark, and those
transactions would be sealed twice.

Fix: give `SealedTxs` a `fence()`, call it once per pool per pass before the `if`, unconditionally, and keep
`clear_orphaned` a pure unmark. Nothing reads the floor with the switch off.

When: before the upstream PR.

### Info

- **I11. The hold-back can fire after the replacement was already packed in the same build, and the doc says
  otherwise** (logic audit).
  - Sequence: R arrives through the iterator's channel while C is independent. R has a higher tip, so it pops first
    and is packed. C pops later, and `holds_nonce` is true because of R itself, so S's remaining nonces wait one build.
    The order stays correct, but the wait is needless.
  - `batch.rs:196-198` and `txn_pool.rs:1351-1354` say "the next build packs the replacement first", which does not
    hold for this ordering.
  - Pre-existing in both switch states: an R that arrives after C was packed is packed too, so one batch carries two
    transactions at one nonce, and one is skipped at execution.
  - Fix for both: plain-skip a candidate whose nonce is at or below the sender's highest nonce already packed in this
    build (`sender_nonces`), checked before `holds_nonce`. Gate the pre-existing half separately: it changes
    switch-off selection.
- **I12. The trait defaults can silently disable the fix.** `TxPool::holds` and `holds_nonce` default to `true`
  (`txn_pool.rs:242-253`). A future pool that marks transactions but does not override `holds` turns the race fix off
  without a compile error. Fix: make both methods required.
- **I13. One counter, three causes.** `late_marks_refused_total` (`sealed_txs.rs:178-179`) now counts refusals because
  execution beat the ack, because of a lag, and because of the orphan pass. At an epoch turn it rises by up to one
  batch per worker without anything being late. Before the image only if the bench report reads this counter;
  otherwise add a label upstream.
- **I14. Doc text.**
  - `sealed_txs.rs:39-42` says "The pool never reads the switch". Since `891e2b962` the pool is built from it. The same
    passage says "the one thing the store does regardless of the switch" is to remember executed digests; it now also
    raises the generation and the floor at every orphan pass.
  - The public `new_with_sealed_tx_keep` doc links the private `pending_limit` (`txn_pool.rs:345`): a rustdoc
    `private_intra_doc_links` warning. CI runs no rustdoc.
- **I15. Hold-backs are not counted.** The presence skip having no counter is already listed (D80); hold-backs are
  not counted either. See L7's fix.
- **I16. Tests.**
  - The code review traced all four new tests and each fails without its fix:
    - `lib.rs:3434` packs both transactions;
    - `lib.rs:3476` packs `[t1, r]`, nonce 1 ahead of nonce 0;
    - `sealed_txs.rs:725` fails under `cc022b4d0`'s design;
    - `env/mod.rs:809` fails when on equals off.
  - No flakiness found. `RacingPool` blocks only a blocking-pool thread, and every wait is bounded.
  - Gaps:
    - The hold-back test depends on equal priority (both tips 0, `tn-reth/src/test_utils.rs:373`), so it does not
      exercise I11's order.
    - The `keeps_sealed` TestPool tests (`batch.rs:939`, `:966`) never reach the presence path.
    - `ThreadCheckedPool`'s runtime-thread guard does not cover the two new calls.

## Residuals re-checked, not re-reported

- **Per-sender slots.**
  - Raised by three sources: code review Medium, logic audit Medium, state transitions Low.
  - Mechanism: reth counts every pooled transaction of a sender against `max_account_slots` (`reth/pool/txpool.rs:
    1851-1860`; TN's default is 256, `tn-reth/src/cli.rs:148`), marked ones included. `891e2b962` doubles only the
    pending cap, and its test pins the slots as unchanged (`txn_pool.rs:2800`, `:2812`).
  - It is U6a's accepted residual (`bench6-g1-notes.md:349`: "including reth's 256 per-sender slots (bench windows are
    16 and 4)"). The delta neither creates nor worsens it. The M16 arm is 600 senders × 16 (`bench6-contract.md:122`),
    so one sender's in-flight plus unsealed count stays near 16, far below 256.
  - For upstream: `891e2b962`'s own rationale (in-flight transactions now share the cap) applies to this cap as well.
    Decide both together: scale `max_account_slots` by `SEALED_TX_KEEP_PENDING_FACTOR` in `build_pool`, switch-gated,
    or state the per-sender cap in the residual.
- **D80.** The doubled cap applies to a forwarding worker's pool too (logic audit N6). Harmless.
- **Other interleavings the presence check does not cover, none new:**
  - A lag clear (accepted).
  - A never-marked copy that a peer's batch mines between `holds` and the pack. Accepted; the window shrinks from the
    whole walk to two calls.
  - A candidate demoted to queued by a balance drop. It is still "held", in both switch states.
  - A marked transaction that is evicted, swept and resent with the same bytes (the D51/L4 family).

## Answers to the brief

### 2a. Switch off = before
Yes. These lines run with the switch off, and none can change a decision:
- `WorkerTxPool::new` delegates with `false` (`txn_pool.rs:332-339`).
- `build_pool` sets `pending_limit(configured, false)`, which returns `configured` (`:425`, `:1549-1558`). The forwarder's
  limits are read before that line (`:421-424`).
- The env passes `false` (`env/mod.rs:556-563`).
- `build_batch` receives `keeps_sealed = false` (`lib.rs:391`, `:403`; `test_utils.rs:24`), and `batch.rs:200`
  short-circuits. No `holds`, `holds_nonce` or `mark_invalid` call is made.
- `clear_orphaned` raises the generation and the floor once per orphan per pool (`sealed_txs.rs:250-258`). Only
  `mark_present` reads them, and it needs a ticket, which exists only when `keeps_sealed` is true (`lib.rs:449`).

No metric or log line was added.

### 2b. Mixed fleet
Safe. The delta changes only local state: this node's pool limits, which of its own pooled transactions it packs, and
its own mark store. Nothing another validator checks depends on these:
- the batch validator is stateless;
- headers, votes and certificates carry digests;
- execution skips duplicate or out-of-order copies identically on every node.

What peers can see is batch contents: fewer stale copies, a replaced sender's later nonces one build later, and at an
epoch turn at most one re-sealed batch per worker.

### 2c. Liveness under the switch
- Nothing is dropped. Every skip lasts one walk: a fresh snapshot per build (`txn_pool.rs:1209-1211`), and an iterator-local invalid set
  keyed by sender (`reth/pool/best.rs:95`, `:112-118`).
- Bounded delays:
  - a hold-back, one build;
  - L7's park, one tick;
  - L6, one wasted copy (the transaction stays pooled);
  - a refused mark at the orphan pass, at most one re-packed batch per worker.
- Batches, headers, votes and certificates are untouched.
- The epoch close gains an O(orphans × pools) floor raise under the store mutex; it cannot fail.
- The doubled cap removes M2's silent drops at bench load.

### 2d. Byzantine or slow peers
- **Peers:** nothing new. The delta reads no peer input.
- **A client:**
  - It can hold back only its own sender, one build per replacement admitted between a snapshot and the walk. Each
    replacement costs a fee bump of at least 10 %.
  - It can fill 10,000 more pending entries and 20 MiB more (reth's `size()`) per worker pool. Those must be funded,
    gapless transactions that execute and pay. reth's own bookkeeping outside `size()` is estimated at 3-4 MB per
    10,000 entries.
- **A slow node:** keeps up to 20,000 pending, and its walk doubles at the cap (L5).

### 2e. Restart and epoch boundary
- **Restart:** the floor and the generation are in memory. A restart starts a fresh store with floor 0 and no live
  ticket. The doubled limits are fixed when the pool is built, so flipping the switch takes a restart, which the
  rolling-restart plan already does.
- **Epoch:** the pool and the store outlive the epoch. The floor is raised at every orphan pass, including a
  same-epoch re-entry, always before the new run's builders start.

### 2f. Determinism
Nothing consensus-visible reads the new state. The presence check adds timing dependence to what this node packs, as
before. Peers validate and execute the result identically.

### 2g. The scope file's questions

**Q1. The presence check: can a transaction that must be packed again be skipped by every later selection, or a sender
be held back build after build?** No.
- Why no skip outlives one build:
  - `holds` and `holds_nonce` are read live (`txn_pool.rs:1270-1276`), and a new snapshot is taken for every build.
  - The hold-back is `mark_invalid` on reth's iterator: a per-iterator `HashSet<SenderId>` (`reth/pool/best.rs:95`,
    `:112-118`, `:205`), created fresh on each `best()` (`reth/pool/pending.rs:108-117`).
  - Nothing after the walk removes on it: only the blob, unsupported and unpackable lists are removed
    (`batch.rs:310-319`).
- A transaction that must be packed again (unmarked by an execution that skipped it, or by an orphan clear) is still
  pooled, so `holds` is true and it takes the normal path.
- A sender is held back on two builds in a row only if a fresh replacement of its own transaction lands between each
  build's snapshot and the walk. That needs the sender's signature and a fee bump of at least 10 % each time. A third
  party can replay only what the sender signed.
- The orderings through the iterator's channel (`reth/pool/best.rs:129-191`):
  - R arrives before C is yielded, and C is not independent: R replaces C in the iterator's `all` map and is packed
    when the earlier nonce pops.
  - C is independent and R is stashed: popping C removes R from `all`, and the hold-back defers R to the next build.
  - R is processed while C is independent: R pops first and is packed, then the hold-back trims S's later nonces
    (I11).
  - R arrives after C was packed: the pre-existing duplicate (I11).

  Each ordering keeps nonce order. The one new ordering that breaks it is L6, which needs eviction plus a tail-only
  resend mid-walk.

The interleavings:
- **(a) Canonical update:** covered. The prune and the stale-nonce discard run under one write lock, and the unmark
  comes after (`txn_pool.rs:1030-1040`). The walk reads the mark before presence (`batch.rs:185`, `:200`). So
  "unmarked" implies "not held", the nonce is not held either, and the candidate gets a plain skip.
- **(b) Eviction:** covered. The sweep unmarks only what the pool no longer holds, under the store lock
  (`sealed_txs.rs:278-292`), and truncation takes descendants along (plain skips). The exception is L6.
- **(c) Fee-bump replacement:** covered by the hold-back (`batch.rs:201-203`), with the one-build cost of I11.
- **(d) The orphan clear and the re-pool:** both finish before any builder starts (`run_epoch.rs:411`).

Not covered, none new: a lag clear (accepted), and the items under "Residuals re-checked".

**Q2. The ticket floor: can a legitimate mark of the new run be refused? What does a refused mark cost, and is it
bounded?**
- **A builder that took its ticket before the pass and sealed after it:** only a closing-run builder can have such a
  ticket.
  - Tickets are taken only at `lib.rs:449`, inside the "next-batch" task on the epoch spawner. The closing run aborts
    and joins those tasks (`run_epoch.rs:613-643`) before the next `run_epoch` runs the pass (`:411`) and starts
    builders (`:413-429`).
  - A new-run ticket therefore equals or exceeds the floor, and the refusal is `ticket < floor` (`sealed_txs.rs:178`).
  - No legitimate new-run mark is refused. Only a later lag can refuse one, as before.
- **A same-epoch re-entry:** the same ordering. An identical digest selected after the pass is marked, because
  `c8659e2fa` stopped writing the executed memory in `clear_orphaned` (test at `sealed_txs.rs:711`).
- **Two worker pools:** every orphan is cleared, and the floor raised, on every pool from
  `get_all_worker_transaction_pools` (`close_epoch.rs:253-263`). Pools outlive runs, so the closing builder's pool is
  in that list. A mark that lands between pool A's clear and pool B's is serialised by B's store mutex. B's own clear
  removes it if its digest is an orphan; otherwise execution clears it.
- **What a refused mark costs:** the batch's transactions stay pooled and unmarked.
  - If the digest is an orphan, the pass re-pools them (`AlreadyImported`) and they are packed once. That is the
    intended repair.
  - If the digest was handed to the engine but has not executed yet, the new run's first build packs them again, and
    every node skips the copies as `nonce too low`. If the execution lands during that walk, the presence check skips
    them instead.
- **Bound:** at most one batch per worker per run change, because each builder has one build in flight and marks
  before it reports (`lib.rs:474-481`). That equals the switch-off cost of the same abort, whose prune never runs.
- **Is the floor raised wherever a late mark could otherwise stick?**
  - When recovery fails partway: yes, the clear runs before recovery.
  - When the node is not an active CVV: yes, the clear runs before the `is_cvv` branch.
  - When the orphan list is empty: no, but no stuck mark is possible then, except the I2 corner (L8).

**Q3. The doubled pending limits.**
- **Switch off, bit-for-bit:** yes, on every path.
  - `new` passes `false` (`txn_pool.rs:332-339`).
  - `build` is now `#[cfg(test)]` and passes `false` (`:373-389`). Its only caller,
    `init_txn_pool_without_maintenance`, is also `#[cfg(test)]` (`env/mod.rs:571-583`).
  - The env passes its switch (`env/mod.rs:556-563`), and test envs default to off.
  - `pending_limit(c, false)` returns `c` (`txn_pool.rs:1549-1558`).
  - The test at `txn_pool.rs:2760` checks every limit, against reth's defaults and an operator's flags, through both
    `new` and `new_with_sealed_tx_keep(false)`.
- **Switch on, any pool without the raised limits:** none in production.
  - The only production constructor is `engine/inner.rs:170` → `RethEnv::init_txn_pool`. That env is built by
    `node.rs:1813-1820` from `reth_switches(parameters)` (`node.rs:2108-2111`), the same source as the builder's
    switch (`engine/inner.rs:587`).
  - The env test at `env/mod.rs:809` pins it.
  - Only `#[cfg(test)]` pools built through `build` keep the configured limits.
  - The forwarder deliberately keeps the configured limits (`txn_pool.rs:421-424`). No other TN code reads the pending
    limit at runtime.
  - `SubPoolLimit::max()` stays at max (saturating), and the test asserts it.
- **What a client can pin now that it could not before:**
  - Per worker pool, 10,000 more pending entries and 20 MiB more by reth's `size()` at the defaults. In general, one
    more configured pending limit, count and bytes.
  - Add reth's bookkeeping outside `size()`: the `by_hash`, `txs` and `by_id` entries, about 250-400 B each (an
    estimate), so 3-4 MB per 10,000 entries. Plus a transient clone of up to 20,000 entries per build.
  - The entries must be pending-valid: funded, gapless, at or above the base fee, and at most 256 per sender, so at
    least 79 senders to fill 20,000. They are packed, executed and paid for, so the pin lasts only until they execute.
  - Multiply by the number of worker pools on a switched-on node (D80).

**Q4. Does the delta change anything a second validator observes, or anything with the switch off?**
- **A second validator:** no message, validation rule, execution path or system call changed. Peers see only this
  node's batch contents (2b). The pool limits, the presence check, the hold-back and the floor are local.
- **The switch off:** no decision changes (2a). The one always-on mutation is the generation and floor raise in
  `clear_orphaned`, which nothing reads without a ticket.

## Not examined
- No build, test run or measurement. The walk and lock costs and the bookkeeping per entry are estimates.
- The bench harness beyond the window figures in `bench6-contract.md`, and its fee-bump behaviour, assumed to be none.
- reth's replacement rules for tip-bearing bumps beyond the iterator, reth's `on_canonical_state_change` beyond the
  functions cited, the retired-pool hand-off, and forwarder internals.
- The e2e tests and configurations with more than one worker, beyond reading the code.
- The rest of the topic outside these six commits, already reviewed in `sealed-keep-report.md`.
