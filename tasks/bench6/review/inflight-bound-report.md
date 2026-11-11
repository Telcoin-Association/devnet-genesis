# Review: inflight-bound (bench 6, RPC admission bound)

Commits, in branch order: `639817091` (config field and `ExecutionBacklog`), `5ef5152a9` (backlog from output numbers),
`74ac00a81` (one backlog shared by node, engine and RPC guard), `998f84a26` (engine starts on its env's backlog),
`f792ef186` (node records forwarded outputs), `256422898` (RPC refuses raw submissions), `74662a889` (config docs),
`1e563ad4c` (e2e test). Branch `bench/bench6-2026-11`. The scope was written at `ae62cc47a`. The branch has since moved to
`c88936999`, which touches only `crates/config/src/node.rs` (two doc lines above this switch) and `env/mdbx_advice.rs`, so
nothing of this topic changed. Line numbers are at `ae62cc47a`. In `crates/config/src/node.rs`, add 2 to get the head line
numbers: the switch doc and field are at 428-439 at head, the default at 561 and the `switches()` entry at 728-735.

How this was produced:
- The repository's code review (`tn-review`) and security evaluation (`tn-security-eval`) ran on the eight commits.
- For the security evaluation these evaluators ran: consensus safety, state transitions (scoped to the three atomics and
  the gates' open flags), DoS, determinism, nemesis, DREAD and STRIDE. Contract safety, crypto correctness and dependency
  audit were not started: the diff has no Solidity, no cryptographic code and no `Cargo.toml`/`Cargo.lock` change.
- Both skills' verification steps ran inline and saw the claims they were checking. So the merge step gave each Medium
  claim to its own blind verifier, which got only a neutral question and the code, never the claim. Both claims held; one
  dropped to Low.
- I checked the central mechanisms against the code myself:
  - every path that sends to the engine;
  - how the engine ends, and that a critical task's exit ends the process;
  - the `--forward-txs` relay's handling of a JSON-RPC error;
  - the forwarder's held-rejection rule;
  - the guard's order of checks.
- The e2e test (`crates/e2e-tests/tests/it/admission.rs`) was read lightly, as evidence. Its results on a local
  four-validator fleet are in `tasks/bench6-g1-notes.md`, "From ST-B".

## Verdict: APPROVE WITH FOLLOW-UPS

There is no Critical or High finding. The bound is consensus-safe and deterministic. It writes nothing another validator
checks. With the switch at 0 it changes no behaviour. I found no interleaving that keeps the gate closed while the engine is
idle.

The one Medium (M1) and two of the Lows (L1, L3) sit on the observer and `--forward-txs` paths. They matter only when
transactions reach validators through an observer or a forwarding node. The benchmark launch scripts do not mention
observers (grep of `benchmark/launch/`), and the generator classifies the validators' own -32003 answers (D47), so its load
appears to go straight to the active validators. If that holds, nothing here has to change before the benchmark image. If
any arm sends load through an observer or a `--forward-txs` node, M1, L1 and L3 must be fixed first, and the verdict becomes
CHANGES REQUIRED.

Counts: 0 Critical, 0 High, 1 Medium, 4 Low, 8 Info (13 after merging two findings both reviews reported), plus 6
unverified notes.

## Findings

### M1. Medium, CONFIRMED (blind). With the honest gates closed, one validator's rejection deletes an observer-forwarded transaction
Fix before the upstream PR. Fix before the benchmark image only if load enters through observers.

Where:
- `crates/tn-reth/src/forward.rs`: the rule and its doc at 1109-1128, held verdict 1215-1235, TryNext keeps it 1241-1248,
  end of chain 1276-1278, removal with no requeue 808-818; -32003 is transient at 162.
- Honest trigger: `crates/tn-reth/src/worker.rs:171`.

The walk was hardened against a lying owner in issue #1167. A first rejection is held, and the walk goes on until a second
validator rejects too or one accepts. The doc states the premise: "A rejection that reaches the end of the chain unconfirmed
stands: no other validator was reachable to consult". The bound breaks that premise. Under load every honest gate closes at
once (D48), and a closed validator answers -32003, which the walk treats as `TryNext`. So the honest validators are
reachable, but none of them gives a verdict.

Sequence:
1. Load is high, so all ten validators' gates are closed.
2. An observer forwards transaction T, whose sender is owned by validator V. V is dialled first (owner routing, 1100-1106).
3. V answers -32000 with a message outside `NODE_LOCAL_MESSAGES`, and the walk holds that rejection. V may be byzantine.
   V may also be honest, with a removed worker: `WorkerRpcAdmission::ensure_active` answers -32000 "worker is inactive".
4. The other nine answer -32003, and each answer leaves the held rejection in place.
5. The chain ends and the held rejection becomes `ForwardOutcome::Rejected`.
6. `spawn_forward` removes T from `pending_forwards` and does not requeue it (808-818). The observer had already told its
   client the transaction was accepted.

Before this topic, one of the nine would have accepted T, and the walk would have counted V's rejection as overridden
(1180-1213). The walk code is older than this topic. What the topic adds is a fleet that routinely refuses together, which
lets one validator censor the accounts it owns whenever the gates are closed. That is most of the time at saturation (D47).

Fix:
- If any hop of the walk answered `TryNext`, treat an unconfirmed rejection as no verdict and requeue. The retention lifetime
  (240 s) still bounds the retries.
- A cheaper partial fix closes only the honest trigger: answer "worker is inactive" with -32603, or add it to
  `NODE_LOCAL_MESSAGES`.

### L1. Low, CONFIRMED (blind; lowered from Medium). A requeue the observer's own pool refuses is lost, and the loss is not counted
Fix before the upstream PR. Fix before the benchmark image only if load enters through observers.

Where: `crates/tn-reth/src/forward.rs:939-958` (`requeue_one`); `crates/tn-reth/src/forward_pending.rs:298-313`.

Sequence:
1. Every gate is closed, so each walk ends `NoEndpointReached`, and `requeue_one` puts the transaction back into the
   observer's pool after `REQUEUE_GRACE`.
2. Observers are not gated (D50), so their own clients keep filling that pool.
3. The pool refuses the reinsert. The causes include a full pool (discard-worst evicts the newcomer), the 256-per-sender
   cap, and an underpriced replacement.
4. `reinserted(hash, false)` removes the pending entry. The transaction is in no pool and no table, and only successful
   requeues are counted (forward.rs:952).

The drop path is older than this topic (#1153, #1372), and forward.rs:934-937 documents it. Evicting the worst transaction
from a full pool is normal mempool behaviour. The topic makes this path run on every pass while the gates are closed. The
real gap is that nothing counts the loss.

Fix: count and log failed requeues. Optionally, keep the entry `RetryDue` when the refusal is anything other than
`DiscardedOnInsert`.

### L2. Low, CONFIRMED (both reviews). From a start to the first finished output, the backlog cannot see the channel to the engine
Fix before the upstream PR. Not needed for the benchmark at K = 2.

Where:
- `crates/types/src/execution_backlog.rs`: the fallback at 88-93; the doc at 48-49.
- `crates/engine/src/lib.rs`: the held count at 337-340; the only production `record_executed` call at 264.
- `crates/node/src/manager/node.rs`: worker 0's RPC binds before replay at 1005-1026, and the replay starts at
  `start_epoch.rs:135-175`.

While no output has finished since the start, `outputs_behind()` returns the engine's held count. That count is at most 8
queued (`MAX_QUEUED_OUTPUTS`) plus 1 executing. It does not see up to 64 outputs in the channel (`TO_ENGINE_CAPACITY`).
Worker 0's RPC is bound, with the node's mode seeded, before replay forwards anything, so during that stretch the gate reads
0.

Sequence (K = 20):
1. The node restarts with a full backlog to replay.
2. Replay fills the channel and the engine queue.
3. Until the first output finishes, the gate reads at most 9 and admits, though execution is up to 73 outputs behind.

At K ≤ 9, including the benchmark's 2, the held count reaches K almost at once and the gate closes. It cannot reopen
early: the held count stays at least 1 until the first completion. On that completion, `record_executed` runs inside the
task (lib.rs:264) before the loop's update (lib.rs:457), so the exact count takes over. The window exists only at process
start, never at an epoch boundary.

The doc also says the engine "may also record its last executed output at start". Nothing does.

Fix: seed `record_executed(last executed number)` at start (replay knows it), or keep a sent-since-start counter and use
`sent.max(queued)` as the fallback. Change or delete the doc sentence either way.

### L3. Low, CONFIRMED (both reviews; I re-read the code). A `--forward-txs` node passes a closed gate's -32003 to its client and tries no other target
Fix before the upstream PR (the docs at least). Fix before the benchmark image only if load enters through a forwarding
node.

Where:
- The relay: `crates/tn-reth/src/rpc_tx_forward/client.rs:218-230`, and the module doc at 1-10.
- The docs: `crates/config/src/node.rs:430-432` (432-434 at head); `crates/tn-reth/src/rpc_fee_cap.rs:40-41`;
  `crates/tn-reth/src/env/rpc.rs:357-359`.

`TxForwarder::submit` treats any JSON-RPC error reply as the target's final verdict. So with target A closed and target B
open, the client gets "txpool is full" and B is never tried. The docs say the forward path is "not gated" and that "TN's
observer forwarder" fails over. That is true of `crate::forward`, but not of this relay. Because all gates tend to close
together (D48), failing over would rarely help; the docs are the real problem.

Fix: say in the switch doc and the module doc that a forwarding node applies no bound itself but relays a target's -32003
unchanged, without failover. Optionally fail over on -32003 without demoting the target.

### L4. Low, CONFIRMED (lowered from Medium by the security evaluation's verifier). Admission ignores fees and goes to whoever polls first
Fix before the upstream PR (docs).

Where: `crates/tn-reth/src/rpc_fee_cap.rs:193-201`, and the check at 289 and 303, before `cap.enforce` at 290 and 304.

While the gate is closed, every submission is refused whatever its fee. When the gate reopens, the window goes to the
client that polls fastest, not to the highest fee. A client can probe the gate state for free with undecodable bytes. The
verifier cited TN's zero-tip policy (`txn_pool.rs:324-330`) to lower this; I did not check that citation.

Fix: document arrival-order admission. Optionally admit above-floor tips while closed.

### Info
- I1 (D48, not worse than stated). When every validator refuses, the observer forwarder does not back off: only an
  unreachable endpoint is demoted (forward.rs:1254-1263), and `REQUEUE_GRACE` delays only a task's first requeue. The
  per-hop debug line (1241-1247) predates this topic.
- I2 (D52). The engine records an output as executed when the sequential task returns Ok (engine lib.rs:252-265), which
  includes the persist. Pipelined persist is not on this branch's run loop: the field is stored at lib.rs:128 and nothing
  reads it. When U12b lands it must record at the durable commit. Note also that an arm file with `pipelined_persist: true`
  on this image runs sequentially without complaint.
- I3. Work done with the switch at 0. It cannot change behaviour; listed under 2a.
- I4 (predates the topic). A shed batch counts under `forwarded_txns_dropped_total{reason="batch_shed"}` although it stays
  pooled (forward.rs:1019-1022).
- I5. The refusal counter also counts undecodable bytes, because the check runs before the decode
  (rpc_fee_cap.rs:196, 289). The contract row should say "refused requests, including undecodable ones".
- I6 (next to D47/D49). At K = 2 the gate closes whenever two outputs are forwarded before the first finishes, even when
  execution keeps up on average. Transactions admitted while the gate is open are not counted until their output is
  forwarded. So K bounds the execution backlog, not the transactions in flight, and a burst admitted while open is
  unbounded. One sentence in D47.
- I7 (for the benchmark). During a rolling restart a gated validator can be held closed by load the ungated validators
  admit, because its backlog follows everyone's batches. Set K the same on every node and leave the flip window out of the
  arm's statistics.
- I8. The refusal is byte-identical to reth's `TxPoolOverflow`. That is by design.

Unverified notes (no verifier checked these, so they are not findings):
- The gate's open flag is a load then a store, not a compare-and-swap (execution_backlog.rs:146-150). The doc already
  bounds the effect at one extra admission or refusal per racer.
- There is one gate per RPC server (env/rpc.rs:374), so two workers' flags can disagree inside the hysteresis band.
- No log line or gauge marks a gate transition. The refusal counter is the only signal, as the U11 notes say.
- The `tn_node_execution_backlog_outputs` gauge is set right after a forward (run_epoch.rs:802), so it samples the cycle's
  peak and rarely shows 0.
- The struct doc's "does not flip on every output" (execution_backlog.rs:99-100) is false at K = 1, which has no band.
- The leftover drain's first phase has no continuity check (close_epoch.rs ~329-343). This predates the topic and can only
  make the gate read low.

## Answers to the brief's questions

### 2a. Switch off = before
Yes. With `rpc_admission_backlog_outputs: 0` no response, decision or code path changes. These lines run with the switch at
0 and did not run before:
- Config: a new field with `serde(default, skip_serializing_if = "is_default")` (config node.rs:436-437, default 559), so an
  existing parameters.yaml parses unchanged and a serialized one gains nothing. The `switches()` entry (726-733) adds one
  field to the existing "node switches" log line and one 0-valued `tn_node_switch` gauge (manager/node.rs:2096-2099).
- Node: one `ExecutionBacklog::new()` per process (manager/node.rs:836). `reth_switches` clones the handle and copies the
  limit (1819, 2112-2113).
- Engine:
  - At construction it takes the env's handle (lib.rs:150-152), and `configure_engine` sets the same handle again
    (inner.rs:78-82, 569-573).
  - Per output: one `Arc` clone (lib.rs:241), and a relaxed `fetch_max` when the output succeeds (262-265).
  - On each arrival and each completion: one relaxed store of the held count (337-340, called at 436 and 457).
- Forwarder, per forwarded output after the send: a `fetch_max`, a backlog read, and
  `gauge!("tn_node_execution_backlog_outputs").set(..)` (run_epoch.rs:801-803). That series is exported with the switch off,
  as the contract says.
- RPC:
  - Per server build: `BacklogBound::new(.., 0)` builds an `AdmissionGate`, drops it and returns the default; no counter is
    registered (rpc.rs:374, rpc_fee_cap.rs:178-182).
  - Per submission: the mode closure is still called once, now into a local, and `ensure_admits` matches `gate: None` and
    returns `Ok(())` (rpc_fee_cap.rs:193-201, 287-289, 301-303).

None of these can return early, error or panic: they are atomics, `saturating_*` and `try_from(..).unwrap_or(..)`. The
topic adds no log line. One series is new with the switch off: the gauge `tn_node_execution_backlog_outputs`. The epoch-close
gauge at run_epoch.rs:501-505 also reads the backlog, but it belongs to another topic (`b77ccbb29`).

### 2b. Mixed fleet
Nothing here can fork the chain, make validators reject each other or stall the fleet. The switch changes nothing another
validator checks:
- no header, vote, certificate, batch, `ConsensusOutput`, EVM block or epoch record;
- no validation rule;
- no epoch-close condition.

The three atomics are written at run_epoch.rs:801 and engine lib.rs:264 and 339. They are read only by the RPC gate, the
local gauge and a local epoch-close metric. The config field is `serde(default)`, `Parameters` has no
`deny_unknown_fields`, and nothing hashes or exchanges it. The switch changes only which raw transactions enter this
validator's own pool, a choice every validator already makes alone.

ST-B ran fleets mixed on this switch and on sealed-keep as one chain in 4 of 4 runs, including a restart. The operational
effect of a mixed window is I7: load moves to the ungated validators, which can keep a gated one closed.

### 2c. Liveness under the switch
No batch digest, header, vote or epoch close is touched. The new writes are non-blocking atomics placed after the existing
send (run_epoch.rs:796-803, with no new await and no new error) and after execution (lib.rs:262-265).

What the switch can now drop or delay:
- A direct client's refused transaction is in no pool and lands only if the client resends it. This is D47; the generator
  drops it on the 22nd refusal.
- An observer-forwarded transaction while every gate is closed: the walk ends `NoEndpointReached`, the transaction is
  requeued after 1 s and forwarded again with the next batch. The ST-B notes report that it landed exactly once in 3 of 3
  runs. It is lost only through M1 (one -32000 rejection while the others refuse) or L1 (the observer's pool refuses the
  requeue).
- A gate cannot stay closed while the engine is idle (2g Q1).

### 2d. Byzantine or merely slow peers and clients
- A slow validator closes only its own gate. An observer then pays one extra round trip for the roughly one in ten
  transactions that validator owns. A `--forward-txs` node that lists it first refuses every client (L3).
- A byzantine validator could not do this before. While the honest gates are closed, it can now drop the
  observer-forwarded transactions of the accounts it owns, by answering one fabricated -32000 (M1). It needs nothing beyond
  its committee seat. An honest validator with a removed worker does the same by accident.
- A client:
  - Each refused request costs the node a few relaxed loads, at most one store, one counter add and a constant error, after
    the JSON and hex parse that every request already costs. Nothing is logged.
  - A client cannot move the backlog. It can read the gate state for free and inflate the refusal counter (L4, I5).
  - To close every gate, a client must pay for enough execution load to saturate the chain: the same spend as saturating
    the chain with the switch off. The difference is that clients see refusals instead of delay, and the first arrival wins
    at each reopen.

### 2e. Restart and epoch boundary
State held in memory: the three atomics (one `ExecutionBacklog` per process), and one `open` flag per RPC server's gate.

On restart:
- Everything is new. Both numbers read `None`, the held count is 0, and every gate starts open (execution_backlog.rs:119).
- The backlog reads 0 until replay forwards something. It then reads the engine's held count until the first output
  finishes, and is exact after that (L2).

On an epoch change, nothing is rebuilt:
- The `EpochManager`, the to-engine channel (created once, "survive the lifetime of the node", manager/node.rs:890-891),
  the engine (started once, 915-924) and the env all live for the process, so the atomics carry over.
- Output numbers are the consensus chain's global numbers (`ConsensusOutput::number`, output.rs:173-175), so nothing needs
  a reset.
- `restart_worker_rpc` only reactivates the worker's admission and fee (engine/mod.rs:343-350). It does not rebuild the
  server, so the gate and its flag carry over too.
- While a worker is inactive, or the node is not `CvvActive`, the gate is not consulted and its flag freezes. The next
  consulted submission re-reads the live backlog.

### 2f. Determinism
Nothing. No iteration order, wall-clock time or thread timing reaches consensus-visible data. The engine gains two atomic
writes, with no await, lock, early return or panic (lib.rs:262-265, 337-340). The gate's timing decides only this node's
pool contents, which validators never had to agree on.

### 2g. The scope's questions
1. **Stuck closed while the engine is idle.** I found no interleaving.
   - Every send to the engine goes through `process_output`: the live path (run_epoch.rs:864, 868), replay
     (start_epoch.rs:175) and the leftover drain (close_epoch.rs:340, 370).
   - `process_output` records the number only after the send succeeds, with no await in between (run_epoch.rs:796-801).
     So a cancelled select cannot split them, and a failed send records nothing.
   - The engine can end by:
     - an execution error (`?` at lib.rs:449, which skips its own `record_executed` at 263);
     - the stream closing (386-387);
     - shutdown (379-380);
     - the test-only `max_round`.
   - The engine is a critical task on the node's task manager (inner.rs:85; manager/node.rs:915). `until_exit` returns an
     error when a critical task exits outside shutdown (task_manager.rs:536-560), so each of those ends the process, and the
     next start has a new backlog.
   - The engine is not per-epoch, so an epoch end never strands a forwarded output.
   - In-process replay of lower numbers can only make the count read low, because both counters use `fetch_max`. After a
     restart, memory is new.
   - A stale held count is ignored once both numbers are known (fixed in `5ef5152a9`).
   - An idle engine has executed everything forwarded, so the backlog reads 0, and the next submission reopens the gate.
2. **No submission to reopen it, or reopening while far behind.**
   - The gate is lazy, but every consulted submission re-reads the live backlog (execution_backlog.rs:142-152). A closed
     flag never blocks its own re-evaluation.
   - Submissions refused earlier in the guard (inactive worker, node not active) skip the gate and only freeze the flag.
   - It can reopen while far behind in three cases:
     - with K > 9, before the first finished output after a start (L2);
     - for outputs committed but not yet forwarded, which are outside the backlog by definition (a forwarder blocked on a
       full channel, or a node whose view of consensus trails);
     - above 73 outputs (D49).
3. **A client refused with -32003.**
   - Lost: a direct client's transaction is lost if the client gives up (D47). An observer-forwarded one is lost only
     through M1 or L1.
   - Duplicated: no. The gate refuses before insertion, a requeued copy of a delivered transaction is answered "already
     known", and a transaction with an earlier acceptance is deferred, not requeued (forward.rs:799-807).
   - Spin: no tight loop, but no backoff either (I1). A pass takes at least the 1 s requeue grace or the walk time,
     whichever is longer, plus the batch cadence. At most 64 forwards run at once. -32003 never triggers the 30 s
     unreachable cooldown.
   - Cost per refused hop: one HTTP round trip and one debug line.
   - Cost per transaction per pass with all ten closed: 10 sequential round trips, a signature recovery on requeue plus
     pool validation, one warn line and one `unreached` count. The budgets are 15 s per transaction and 120 s per batch,
     and the unwalked tail is requeued.
4. **RPC abuse.** The refusal path does nothing expensive before the check.
   - What runs before it already ran before this topic and is cheap: the jsonrpsee body and JSON parse, the hex decode of
     the `Bytes` parameter (bounded by the request size limit), a trace log, `admission.ensure_active`,
     `ensure_active_worker`, and the mode read with `ensure_can_submit`.
   - On both methods the gate runs before the RLP decode in `cap.enforce` and before reth's signature recovery and pool
     validation (rpc_fee_cap.rs:289/290 and 303/304).
   - I found no client-callable method that reaches a validator's pool without the gate:
     - TN's own RPC files add only simulation, fee and fill methods (`callBundle`, `call`, `estimateGas`, the trace
       methods, `fillTransaction`, the gas-price methods);
     - the guard replaces both submission methods on every transport that serves `eth` (env/rpc.rs:395-398);
     - `--forward-txs` relays to validators, whose own gates apply;
     - `eth_sendTransaction` needs a local signer, and none is registered.
   - The `tn` namespace was listed (`crates/execution/tn-rpc/src/rpc_ext.rs`, all read methods) but not read in full.
5. **Epoch boundary.**
   - `number()` is the consensus chain number, contiguous across epochs: replay checks contiguity (start_epoch.rs:157-164),
     and the live forwarder skips stale outputs and errors on a gap (run_epoch.rs:827-842).
   - At the close, the forwarder sends the closing output (860-865) and stops. Once that output executes, forwarded equals
     executed, and the backlog reads 0. The next epoch's first output reads 1.
   - Outputs drained at the close without forwarding (run_epoch.rs:698) are never recorded.
   - The backlog cannot wrap: both subtraction and encoding saturate (execution_backlog.rs:90, 186).
   - It cannot read huge: at most 73 (64 in the channel, 8 queued, 1 executing).

## What the e2e test shows (ST-B, four local validators)
- With one validator executing 500 ms late per output, its gate closed 3.5 s into the load. It answered -32003 while the
  other three admitted.
- A refused transaction was in no pool and landed only when resubmitted. After the load stopped, the same bytes were
  admitted and landed once.
- The bound-0 control admitted throughout and served no refusal series.
- An observer never answered -32003. It requeued, and everything landed once after the gates reopened.

These runs had no byzantine validator and no full observer pool, so they do not exercise M1 or L1.

## Not examined
- How the batch builder, worker and proposer behave with an empty pool while every gate is closed. The e2e runs with closed
  gates did not stall.
- reth's pool eviction and fee ordering, beyond what L1 cites; TN's zero-tip policy, which L4's verifier cited.
- The startup order beyond worker 0's RPC binding before replay, and when the metrics recorder is installed. The e2e test
  shows the refusal counter served at 0 before any load.
- `payload_builder.rs` internals: I took "executed" to include the persist, as its doc says.
- The `tn` RPC namespace in full.
- The benchmark arms' RPC targets: whether any arm sends load through an observer or a `--forward-txs` node decides
  whether M1, L1 and L3 must be fixed before the image.
- The default file-log filter, which decides the log volume of I1.
- Pipelined persist (U12b), which is not on this branch's run loop.
- The e2e test code, beyond a light read.
