# Topic review: digest-dedupe (#1807, switch `digest_dedupe`)

Reviewed 2026-11-11 against `bench/bench6-2026-11` at head `dc7855cc6` in `/home/drtnarg/coding/telcoin/telcoin-network-b6`.
The diff is `git show --format= 478dd3d23 93e9d7c21 8bc341967 7fdcb9ff5` (4 commits, about +956 lines with tests).
Line numbers are at head. `proposer.rs` lines differ from the topic diff because a later commit of another topic
(c8e5ae7be, "keep a digest's first receipt across a re-queue") touched it. A verifier checked that c8e5ae7be does not change
the dedupe logic or its tests.

## Verdict: APPROVE WITH FOLLOW-UPS

There are no Critical, High or Medium findings, and nothing has to change before the benchmark image.

- **Switch off:** every path is the previous behaviour. The only additions are two counters that stay at 0 and a 20-byte
  copy feeding a debug field.
- **Mixed fleet:** cannot fork, cannot make validators reject each other, and cannot stall the fleet.
- **The central question:** I found no path on which either half drops the only live copy of a digest. In the worst cases
  a batch is delayed until the node's next own commit or the next `run_epoch` start. Its cache row survives either way.
- **Before the upstream PR:** fix the config doc (finding 3). Two tests and a few doc and metric changes are recommended.

### How the review ran
- **Code review:** the repository's `tn-review` method, run as one agent.
- **Security evaluation:** seven of the ten `tn-security-eval` agents (consensus safety, state transitions, DoS, determinism,
  nemesis logic audit, DREAD, STRIDE).
- **Not started**, because their subject cannot apply to this diff:
  - crypto correctness: no hashing, signature or key code changed;
  - contract safety: no Solidity;
  - dependency audit: no `Cargo.toml` or lock change. `lru` and `parking_lot` were already dependencies at
    `crates/consensus/worker/Cargo.toml:20-21`.
- **Verification:** all 26 raw findings were merged into 12 and sent to `findings-verifier`. Findings 1 and the
  stuck-header case were verified individually, the other Lows in batches, plus Infos 9 and 10.
- **Result:** 0 of 8 verified findings were refuted. Five Lows were downgraded to Info, and one (finding 1) I keep at Low
  against the verifier's Info (reason given there).
- No `cargo` was run. Everything below comes from reading the code and the existing tests.

## Findings (most severe first)

### 1. A report landing between row eviction and the committed-own-headers notice is dropped, then suppressed for the rest of the run
- **Severity:** Low. The verifier rated it Info; I keep it at Low because the window is widest in an execution-bound run,
  which is what the bench is.
- **Status:** PLAUSIBLE. The mechanism is confirmed by code trace. The harmful sequence has not been observed.
- **Where:**
  - `crates/consensus/primary/src/consensus/state.rs:752-807`: inside the per-subdag loop are the run-ahead gate (`:756`)
    and `sequence().send` (`:791`). The `committed_own_headers` send comes after the loop, at `:809-813`.
  - `crates/node/src/manager/node/run_epoch.rs:791` → `:1420-1434`: rows are evicted when an output is forwarded.
  - `proposer.rs:1138-1150`, `2354-2364`: the drop. `proposer.rs:901-912`: committed headers are removed with no re-queue.
  - `worker.rs:386-404`, `505-507`: the suppression and the mark.
- **The mismatch:** the worker treats a digest as committed when its `OurNodeBatchesCache` row is gone. The proposer
  treats it as committed only when the notice removes its header from `proposed_headers`. The notice is sent once per
  commit batch, after every subdag of that batch has passed the run-ahead gate.
- **Sequence:**
  1. A commit batch holds subdag i, which carries own header H with digest D, and a later subdag j.
  2. Subdag i is sequenced and forwarded, and D's row is evicted. The gate holds j while execution lags by about 1,000
     rounds (`MAX_COMMIT_RUN_AHEAD_ROUNDS`, `types/src/primary/mod.rs:217`).
  3. A client resends exactly D's transaction set. The builder rebuilds a byte-identical batch with digest D. The worker
     finds no row, so it seals D, writes a new row, reaches quorum and reports D.
  4. The proposer still tracks H, so it acks D and drops it as `proposed`. The worker marks D.
  5. j is released and the notice removes H as committed. No copy of D is proposed again.
  6. The new row is never evicted and the mark stays in the LRU, so every later identical resend in this run is
     suppressed too.
- **Outcome:** with the switch off, the re-report would have ridden a fresh header (residual R1). Only transactions that
  D's own execution skipped are affected (the bench-5 `0x9c01a8c5…` pattern). They are delayed, not lost: the surviving
  row is re-pooled by `orphan_batches` at the next `run_epoch` start (`run_epoch.rs:411`).
- **Reachability:**
  - With a single-subdag batch, the window is microseconds, against a build plus a quorum round trip.
  - In a run that saturates the gate, it can stretch to seconds (the verifier's caveat, medium confidence).
  - With `sealed_tx_keep` on, D's transactions stay out of the builder until D executes, which closes the window.
- **Fix options:**
  - (A) Document it as residual R6 next to `queue_digest`.
  - (B, preferred if code changes) Send each subdag's own committed rounds right after its `sequence().send`, inside the
    loop at `state.rs:791`, and keep the commit-accounting check after the loop. The notice then always precedes that
    subdag's eviction.
  - (C) Have the ack say whether the digest was queued or dropped, and let the worker mark only queued digests. This
    changes the worker-primary protocol.
- **Fix before:** the upstream PR (A at minimum). Not needed for the benchmark image.

### 2. No test runs the real worker against the real proposer; two branches are tested only partly or not at all
- **Severity:** Low. **Status:** CONFIRMED.
- **Where:** `worker.rs:603-632` (the tests use `ScriptedPrimary`); `proposer_tests.rs:1581-1588` (`send_digest` bypasses
  `WorkerReceiverHandler`); `worker.rs:544` (`unwrap_or(false)`).
- **The gaps:**
  - The worker's suppression depends on "an acked report means the proposer holds the digest until commit or epoch end".
    That holds in the code (`network/mod.rs:2799-2813`, `proposer.rs:1418-1420`) but is argued only in doc comments.
  - The commit-path re-queue followed by a fresh report is tested only at index level (`proposer_tests.rs:3322-3366`).
    The cancel-path version is tested end to end (`:3216-3270`).
  - The fail-open on a store read error is never exercised: `MemDatabase::contains_key` cannot fail.
- **Failure scenario:** a future `proposed_headers.remove` with no re-queue would make the worker suppress re-seals of a
  digest nobody holds, and no test would fail.
- **Fix:** add two proposer tests with the switch on.
  1. Run `WorkerReceiverHandler::report_own_batch` against the real proposer. Report D twice, then again once its header
     is tracked. Expect the payload `[D]`, then an empty header, and a suppressed count of 2.
  2. Propose D1 at round 2 and D2 at round 3, then send `committed_own_headers((3, vec![3]))`. A fresh report of D1 must
     be dropped as `pending`, and D1 must appear exactly once in the next header.
  - Optional: a store that fails on demand, for the read-error branch.
- **Fix before:** the upstream PR (recommended).

### 3. The switch's config doc misstates when the worker suppresses a seal
- **Severity:** Info (documentation). **Status:** CONFIRMED.
- **Where:** `crates/config/src/node.rs:372-377`; `worker.rs:519-521`.
- **`node.rs`:** it says "the worker accepts a batch whose digest is already in its own batches cache". The code also needs
  a mark from this worker's latest acked seal (`worker.rs:543-544`). Its own doc (`:524-529`) says the row alone is not
  enough.
- **`worker.rs:519-521`:** it says the proposer "acks the digest and queues it". With the proposer half on, it may ack
  and drop the digest as already held (`proposer.rs:1139-1149`).
- **Failure scenario:** an operator or bench analyst expects a restart or a `FailedToReport` to suppress seals, and
  misreads `tn_worker_duplicate_digest_suppressed_total`.
- **Fix for `node.rs`:** "the worker skips a sealed batch whose digest the primary already acked for this worker's latest
  seal of it and whose own-batches cache row is still present. It is neither sent for a vote nor reported again. A cache
  row alone does not count. The proposer acks every report but drops a digest it already holds: pending, in the header
  being built, or in an own header proposed and not yet committed or re-queued."
- **Fix for `worker.rs`:** say "acks it, and either queues it or drops it because it already holds a copy".
- **Fix before:** the upstream PR.

### 4. A tracked own header that never commits holds its digests until a later own commit
- **Severity:** Info. **Status:** CONFIRMED, with the corrections below.
- **Where:** `proposer.rs:898-961`, `992-1019`, `2363`; `certifier.rs:780`; `worker.rs:386-400`.
- **What happens:** while a header stays in `proposed_headers`, both halves suppress identical re-seals of its digests. The
  digests return to a lane when an own header at a later round commits; otherwise orphan recovery restores them at the next
  `run_epoch` entry. Three kinds of header stay tracked:
  - **Certified but never in a committed leader's history:** occasional under load; the delay is a few rounds.
  - **Cancel report dropped by `try_send`** into a 64-slot channel: practically unreachable.
  - **Stored header re-sent after it already committed** (restart or max-delay tick): here only the proposer drops the
    re-report. The worker does not suppress it, because the row was evicted at commit and the marks are empty after a restart.
- **No loss:** none of these drops a batch. Its row survives until it commits or is re-pooled by orphan recovery.
- **Fix:**
  - Correct the `DigestDedupe` doc, which says such a header "stays tracked until the epoch ends". It should say "until
    an own header at a later round commits, or the epoch ends".
  - Optionally, test the first case.
- **Fix before:** the upstream PR (doc wording).

### 5. `held()` visits every tracked own header on every new report
- **Severity:** Info. **Status:** CONFIRMED; the code documents the trade-off at `proposer.rs:~2326-2332`.
- **Where:** `proposer.rs:2362-2363`, run synchronously in the proposer loop (`:1419-1420`).
- **Cost:** for a digest not already held, `any()` cannot stop early, so a report costs O(H) payload lookups.
  - H is bounded by the own headers tracked since the last own commit; the commit path re-queues every tracked header at
    or below the highest own committed round.
  - At H = 1,000 (about 8 minutes with no own commit) that is about 20-40 µs per report.
  - A whole 24-hour epoch with no own commit is the worst case: about 5-8 ms per report. The 172k headers themselves
    already cost about 170 MB with the switch off.
- **Fix (optional):** a count map of the digests in tracked headers, filled in `landed()` and decremented at the three
  `proposed_headers.remove` sites. It must also cover the R3 re-send paths, or it drifts. Alternatively, add a gauge for
  `proposed_headers.len()`.
- **Fix before:** neither.

### 6. A proposer-side drop cannot be traced at info level
- **Severity:** Info. **Status:** CONFIRMED, with caveats.
- **Where:** `proposer.rs:1140-1150` (`debug!`); `tn_primary_duplicate_digest_suppressed_total` has no labels
  (`primary/src/metrics.rs:167`); `worker.rs:496` (the error has no digest).
- **Caveats:** the builder's error line carries the digest in its span (`batch-builder/src/lib.rs:393`, `:517`), and
  `batch reported` logs the digest at info on every success.
- **Fix:**
  - Label the counter by `where`, following `digests_requeued_total{cause}`.
  - Optionally log the drop at info on `consensus::metrics`.
  - Add `digest` to `worker.rs:496`.
- **Fix before:** the upstream PR (recommended). Useful for bench analysis too.

### 7. An evicted mark followed by a failed re-seal removes the row of a digest the proposer still holds
- **Severity:** Info. **Status:** PARTIALLY VALID. This predates the switch.
- **Where:** `worker.rs:403`, `:416`, `:451`, `:474`.
- **What happens:** if D's mark has fallen out of the 4,096-entry LRU, an identical re-seal is not suppressed. That seal
  overwrites the row, and if its quorum fails the row is removed.
- **Why it is pre-existing:** with the switch off this happens on every identical re-seal, so the switch makes it rarer.
- **Why it rarely matters:** after an `Err` the builder keeps the transactions pooled (`lib.rs:512-521`), and the proposer
  still holds D.
- **Optional hardening:** on failure, remove the row only if this seal created it.

### 8. Residual R4 ends sooner than stated
- **Severity:** Info. **Status:** CONFIRMED.
- **Where:** `run_epoch.rs:411`.
- **What happens:** `orphan_batches` runs at every `run_epoch` entry (epoch boundary, mode-change re-run, restart) before
  any batch builder starts. So after a failed eviction, the transactions wait until the next run, which may come well
  before the next epoch.

### 9. A suppressed seal is counted by the builder but not by the worker
- **Severity:** Info. **Status:** not verified (Info).
- **Where:** `worker.rs:397-399` vs `:511`; `batch-builder/src/lib.rs:~462-475`; `worker/src/metrics.rs:90-94`.
- **What happens:** the builder's `batches_sealed_total` and seal-duration histogram include suppressed seals; the worker's
  `batches_sealed_total` does not. The gap between them equals `tn_worker_duplicate_digest_suppressed_total`.
- **Fix:** say so in the counter doc. Bench analysis should subtract it.

### 10. The `sender` field is not behind the switch
- **Severity:** Info. **Status:** not verified (Info); three agents agreed.
- **Where:** `execution.rs:322`, `:333-339`.
- **Cost:** `tx.signer()` is alloy's `const fn` returning a stored 20-byte `Address`, so there is no recovery. See 2g-Q5.

### 11. The pending index matches the lanes by convention only
- **Severity:** Info. **Status:** not verified (Info).
- **Where:** `proposer.rs:2335-2391`.
- **Why it matters:** see 2g-Q2. A future lane removal that skips `drained()` would leave a phantom count. That digest's
  reports would then be dropped, and its re-seals suppressed, for the rest of the epoch.
- **Fix:** a test-only check that the counts sum to `pending_digests_len()`.

### 12. Documentation of the residuals and the motivation
- **Severity:** Info.
- **Contract row:** residual R3 (a report before a stored-header re-send is not deduplicated, `proposer.rs:1133-1135`) is
  in the code doc but not in the contract row (`tasks/bench6-contract.md:41`), which lists only R1 and R2.
- **Commit message:** 93e9d7c21 cites the bench-5 `FailedToReport` rebuild loop (85 rebuilds) as motivation. A failed
  report sets no mark, so the worker half does not change that loop. That loop is D14 and stays out of scope.

## Answers to 2a-2g

### 2a. Switch off = before
Yes. The only lines that run with the switch off and did not run before are listed here. None can change behaviour.

- **Worker:**
  - `.with_digest_dedupe(false)` (`worker.rs:138`) evaluates `false.then(..)` to `None` (`:261-264`). Nothing is
    allocated.
  - The `None` initialiser (`:242`) and its clone (`:204`).
  - Two `if let Some` checks that are not taken (`:386`, `:505`). The quorum, cache insert, publish, report and record
    sequence between them is unchanged.
- **Proposer:**
  - `digest_dedupe.then(..)` at `proposer.rs:313-317` gives `None`; the metrics lookup inside the closure is not
    evaluated.
  - The run loop calls `queue_digest` (`:1420`). With the switch off it runs exactly the old
    `entry(worker_id).or_default().push_back(digest)` (`:1153`).
  - Three `if let` checks that are not taken: `:1050`, `:1103-1105` and `:1307`.
  - The drain binds the same iterator to `drained` and returns the same `VecDeque`.
- **Metrics (acceptable):**
  - `tn_worker.duplicate_digest_suppressed_total{worker}` (`worker/src/metrics.rs:94`) and
    `tn_primary.duplicate_digest_suppressed_total` (`primary/src/metrics.rs:167`, via `derive(Metrics)`) are registered
    and read 0.
- **Log field (acceptable, ungated):**
  - `execution.rs:322` adds `let sender = tx.signer()`, a 20-byte copy, plus the `%sender` field on a debug line.

### 2b. Mixed fleet
Safe. `Parameters` never goes on the wire; `switches()` feeds only local metrics and logs (`node/src/metrics.rs:225`,
`manager/node.rs:2076`), and the switch is read only when the per-run proposer and worker are built. Another validator can
see only three effects:

- **Own header payloads carry fewer duplicate digests** and are more often empty. What voters check:
  - payload length ≤ `MAX_HEADER_NUM_OF_BATCHES` (`types/src/primary/header.rs:166`);
  - known worker ids (`state_sync/header_validator.rs:141`);
  - batch availability (`:104-128`).

  Voters check no duplicates, no minimum and no order. The certifier ignores the payload.
- **Header timing:** `enough_digests` (`proposer.rs:1481`) fires less often, so headers go out on the min or max delay
  instead. Voters do not check this.
- **Fewer worker requests:** the worker sends no quorum request or `publish_batch` gossip for a suppressed re-seal
  (`worker.rs:386-400`).
  - The earlier seal already reached quorum, so 2f+1 peers hold the batch.
  - Peer batch validation is stateless per batch (`batch-validator/src/validator.rs:82-99`), so a skipped repeat cannot
    invalidate a later batch.

Execution reads only the committed sub-dag (`executor/src/subscriber.rs:1087-1150`), so two nodes with different settings
execute the same output. The switch cannot fork the chain, cause rejected headers, votes, certificates or batches, or
stall the fleet. The only fleet risk during the flip is the rolling restart itself.

### 2c. Liveness under the switch
Nothing is dropped. Two things can be delayed:

- **A stuck tracked header (finding 4):** its digests wait until an own header at a later round commits; otherwise
  orphan recovery restores them at the next `run_epoch` entry.
- **The finding-1 window:** transactions that D's execution skipped wait for orphan recovery.

In both cases, with the switch off an identical re-seal could ride a fresh header and rescue the transactions, at the cost
of a duplicate. With the switch on, that rescue is lost only in these cases.

Unaffected:
- **Headers, votes and epoch close:** `queue_digest` is synchronous and runs after the ack. Empty headers are still
  proposed. Consensus shutdown is checked before the dedupe check (`worker.rs:382-384`).
- **No busy loop:** a suppressed seal answers `Ok`. The builder then prunes the transactions, or `keep_sealed` re-marks
  them under D.

### 2d. Byzantine or slow peers, and clients
- **No remote access to the new state:**
  - `our_digests` is fed only in-process (`network/mod.rs:2797-2813`, `network-types/src/local.rs:60-70,128-139`), and
    `check_worker_id` (`:2784-2794`) ties each report to its worker.
  - Marks are set only after our own primary acks (`worker.rs:505-507`).
  - A peer can only withhold votes, which fails the seal and sets no mark.
- **Slow or poorly connected peers** can only raise H, the number of tracked own headers. Finding 5 bounds the cost:
  about 20-40 µs per report at H = 1,000, about 5-8 ms in a whole epoch without an own commit. Only the proposer
  loop of the affected node pays.
- **A single Byzantine validator (f = 1)** cannot keep our certified headers out of every leader's history.
- **Clients:**
  - An identical resend now costs one LRU lookup and one store point read, instead of a quorum round, a header slot and an
    execution pass.
  - A client that varies batch composition is unaffected by this switch; `sealed_tx_keep` covers that.

### 2e. Restart and epoch boundary
- **Lifecycle:** all of the new state is in memory and is rebuilt for every `run_epoch`.
  - Worker: `run_epoch.rs:358-361` → `worker.rs:138`, `261-264`.
  - Proposer: `primary.rs:106-117` → `proposer.rs:313-317`.
  - Both run on the same per-run `epoch_task_manager` (`run_epoch.rs:226`) and are torn down together (`:613-644`).
  - Every node-mode change fires consensus shutdown and re-enters `run_epoch` (`manager/node.rs:1767-1793`).
  - I found no path where the proposer is rebuilt or absent while the same worker keeps getting acks:
    - If no proposer is subscribed, `QueChannel::send` returns `Ok` without queuing (`consensus_bus.rs:748-750`). The
      ack channel then closes, the seal returns `FailedToReport`, and no mark is set.
    - `our_digests` is per run (`consensus_bus.rs:1988`, `2014`, `2070-2073`; `run_epoch.rs:148`).
- **Restart:** both halves start empty and fail open. Rows survive, and `orphan_batches` re-pools them before any builder
  starts (`run_epoch.rs:411`; `close_epoch.rs:236-297`). A re-sent stored header enters `proposed_headers` without passing
  the index (R3).
- **Epoch change:** the marks and the index die with the run. The next epoch's digests differ, because `epoch` is part of
  the batch.

### 2f. Determinism
Nothing that every validator must compute depends on the new state.

- `held()` returns yes or no from a BTreeMap, the `in_flight` list and IndexMap lookups. The LRU is never iterated.
- Drain order is unchanged (`proposer.rs:1079-1102`), and the payload is built in drain order (`:437`).
- Whether a duplicate is dropped depends on timing, but that only shapes this node's own payload, which peers certify
  as-is. Payloads already depended on timing with the switch off.
- `execution.rs:322` does not change what executes or in what order.

### 2g. Topic questions
**Q1. Can either half drop the only live copy of a digest?** No. Every path, and whether a later legitimate report is
accepted:

| Path | Worker half | Proposer half | Later report |
|---|---|---|---|
| Success | Mark after ack (`worker.rs:505-507`); row kept | Queued → in flight → tracked | Dropped while held (correct). Accepted after commit (R1), except in the finding-1 window. |
| Failed report | No mark (popped at `:403`); row kept | Never queued: a dropped message drops the ack sender | Accepted |
| Report times out after the ack | Unreachable: the local path has no timeout, and the ack resolves the await | Holds D | n/a |
| Primary restart with the worker alive | Unreachable: both are rebuilt per run | — | — |
| Process or worker restart | Empty marks | Empty index | Accepted. Rows re-pooled by orphan recovery. A re-sent stored header may duplicate (R3). |
| Epoch change | Marks dropped | Index dropped | Rows re-pooled; new digests |
| Cancelled header | Mark and row kept | Digests moved to the lanes and counted (`proposer.rs:992-1019`, `1050-1052`) | Dropped as `pending`; D rides the next header |
| Expired (commit-past) header | Kept | Moved and counted (`:928-954`) | Dropped as `pending`; next header |
| Stored header re-sent (restart or max-delay tick) | Unchanged | Re-inserted without a check (`:1182-1225`, `:1543-1563` → `:1305`) | Possible duplicate (R3) |
| Proposal task fails | — | `result?` (`:1292`) → run returns `Err` (`:1439`) | Node stops; same as a restart |
| Certified, never committed | Suppresses | Held | Dropped until a later own commit, else orphan recovery (finding 4) |
| Committed | Row evicted | Header removed | Accepted (R1), except in the finding-1 window |

**Q2. Can the index and the lanes disagree?** Not today.
- The lanes change only at `proposer.rs:1153`, `1055-1058` and `1101`, and each site updates the counts (`:1151`,
  `:1050-1052`, `:1103-1105`). The counts therefore equal the multiset of lane entries at every step, and the warn at
  `:2383-2387` is unreachable.
- One digest cannot sit in two lanes, because `worker_id` is part of the batch digest (`sealed_batch.rs:97-101`).
- When two drained copies collapse into one IndexMap payload entry, the count is still decremented twice and re-queued
  once, so it stays exact.
- `in_flight` is non-empty only between a drain and `landed()`. No header is built while one is pending (`:1459-1463`),
  and a failed proposal is fatal, so it is never stale while the proposer runs.
- If the warn ever fired, the index would fail open: a missing count only lets a duplicate through. The only harmful drift
  is a phantom count (finding 11).

**Q3. Memory bounds.**
- **Worker:** an LRU of at most 4,096 keys, pre-allocated, about 0.4 MB per worker at most, per run.
- **Proposer:**
  - `pending` has one entry, about 45-70 B, per distinct pending digest. It mirrors the lanes, which already had no count
    limit before this change.
  - `in_flight` holds at most `max_header_num_of_batches` (10).
  - Both are rebuilt every run.
- **Faulty local worker:** duplicate reports are now dropped, which is better than before. Distinct digests grow the lanes
  and the index one for one, as before. That is limited by the seal rate (each seal needs a quorum), by one report in
  flight per worker, and by the 10,000-slot channel (`consensus_bus.rs:569-570`).
- **Nothing remote** can reach either structure.

**Q4. With the switch off, are the lanes, drain and payload identical, including order?** Yes.
- Reports go to the back of their lane as before (`:1153`), and the re-queue prepend is untouched (`:1055-1058`).
- The lane walk, the cap, `next_lane` and `pop_front` are unchanged from `7fdcb9ff5^` (`:1079-1102`).
- The payload is built from the drain in order (`:437`).
- `test_digest_dedupe_off_queues_every_report` (`proposer_tests.rs:3278`) pins this. Every earlier proposer test runs with
  `Parameters::default()`, which has the switch off (`node.rs:551`).

**Q5. Cost and information concerns of the `sender` field.**
- **When debug is off:** the only cost is the 20-byte copy (alloy `const fn signer`, about 1 ns per transaction; no
  recovery or allocation). The field is built only when the `engine` debug callsite is enabled, and only on the skip arm.
- **When debug is on:** the EIP-55 `Display` costs one keccak over 40 bytes, about 0.3-1 µs. At bench-5's 37,683 skips
  per node that is about 20-40 ms of CPU and about 1.9 MB of log, against about 215 µs per transaction of execution.
- **Information:** the sender is public, recoverable from a batch broadcast to every validator and from committed
  output, so there is no disclosure concern.
- **The real cost risk** is running the `engine` target at debug at all (the 4 GB/h incident), not this field.

## Note for the benchmark (inference, not verified)
With `sealed_tx_keep` on, a pending batch's transactions are kept out of new builds until that batch executes. Identical
re-seals of a pending digest, which the worker half suppresses, then become rare. Expect
`tn_worker_duplicate_digest_suppressed_total` to stay near 0 in an arm that has both switches on. Judge the proposer
counter and the "duplicate digests executed = 0" check instead.

## Not examined
- **No build, test or `cargo` run.** Test coverage was judged by reading. The window of finding 1 was not measured: how
  the subscriber's base-block wait interacts with the run-ahead gate in a saturated run.
- **Another topic's interaction:** `keep_sealed` re-marking after a suppressed seal that comes after D executes
  (`batch-builder/src/lib.rs:856-864`). It could leave the transactions marked as sealed until orphan recovery. It
  matters only inside the finding-1 window or R4.
- **Not checked:** that the previous run's builder tasks are aborted before the next `run_epoch` begins.
- **Out of scope:** the epoch-boundary `FailedToReport` loop (D14, case S6). Other topics' commits were read only where
  this topic calls them.
- **Not run:** the crypto-correctness, contract-safety and dependency-audit agents, for the reasons given above.
