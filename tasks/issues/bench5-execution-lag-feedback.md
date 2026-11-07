# A lagging node's signer-recovery jobs land on top of its own block builds, so the lag feeds itself

## Problem

Under saturation, a validator whose execution trails the block leaders' by more than about one commit latency switches
into a slower execution mode and stays in it until the load ends. In the same minute that its subscriber starts waiting
for local execution before assembling outputs (stage S7), its `finish` cost rises from 10-12 to 17-19 µs/tx and the
E4 signer-recovery job's wall time from 13 to 19-21 µs/tx. Nothing else changes: persist, the EVM loop and the state
root stay within a few per cent of the other nodes. The node is then 2-3 % slower than the commit rate, so its backlog
grows for as long as the load lasts.

In run r20261107-1504 this happened to v09 at 600 × 4 and to v01, v03 and v05 at 600 × 16. Those three refused 14,802,
11,969 and 5,747 votes as execution-behind, the starvation described in `bench5-execution-behind-vote-starvation.md`
(A2 vote-path.md:13). They reached both loaded epoch closes 11-27 s late, and neither loaded epoch record carries
their votes (both formed at exactly 7 of 10, A3 boundary.md). Their generators saw a 21-35 s seen − land gap
(S7 + S10, triage (f)). The restarted v05 closed its execution gap by only 7 outputs/min under load (A3 recovery.md).

The cause is two bench-5 changes interacting. E4 (`signer-reuse`, 9039198de) runs signer recovery on the global rayon
pool, which `finish` also uses. A rayon pool serves work injected from outside it only after the work already split
across its workers has drained. The F1 subscriber wait (S7) admits each output to the engine at the moment the next
execute task starts. So on a lagging node most recovery jobs run on top of an execute, and every `finish` call during
that time waits for the job.

## Evidence

Run r20261107-1504, image 067639def. Windows as in A4n f2.json: sat4 (600 × 4) 16:58:16-17:04:16, prekill (600 × 16)
17:41:32-17:54:44, post-restart 17:59:44-18:21:32. Per-output data: `output queued`, `signers recovered`, `output
executed`, `output execution task finished` and `waited for execution before assembling the output`, streamed from all
11 unit logs. The scripts are in the scratchpad (`IF/bin/overlap.py`, `IF/bin/onset.py`). "Overlapped" means another
output's recovery job (start = log time − `recover_ms`) intersected this output's execute span (task start + `execute_ms`).

1. **Only the two phases that use the rayon pool get slower.** A4n f2.json, prekill: `finish` v01 18.2, v03 17.1,
   v05 18.7 µs/tx vs 10.2-11.6 on the other seven; signer job 20.6 / 18.5 / 20.9 vs 13.0-13.2; evm 26.8-27.0 vs
   25.7-26.5; root 49.5-50.9 vs 47.0-49.2; persist 199.5 vs 198.2-199.8. At light8 and light16 all 11 nodes match:
   finish 4.4-4.9, job 12.1-13.4.
2. **Within each node, `finish` depends on whether a job ran during the execute.** µs/tx:

   | node / window | overlapped outputs | finish overlapped | finish not overlapped | root over. / not | evm over. / not |
   |---|---|---|---|---|---|
   | v01 prekill | 312 of 443 (70 %) | 22.6 | 7.1 | 50.1 / 50.5 | 26.9 / 26.7 |
   | v03 prekill | 302 of 446 (68 %) | 21.6 | 7.1 | 49.5 / 49.6 | 26.9 / 26.5 |
   | v05 prekill | 305 of 442 (69 %) | 23.3 | 8.0 | 50.9 / 50.9 | 27.1 / 26.7 |
   | v02 prekill | 192 of 455 (42 %) | 16.6 | 6.8 | 49.9 / 48.6 | 26.6 / 26.2 |
   | v04 prekill | 166 of 458 (36 %) | 15.8 | 6.7 | 47.5 / 46.8 | 25.9 / 25.5 |
   | v09 prekill | 190 of 455 (42 %) | 16.3 | 6.7 | 49.9 / 48.5 | 26.8 / 26.2 |
   | obs11 prekill | 150 of 457 (33 %) | 14.7 | 5.8 | 45.9 / 45.2 | 24.9 / 24.8 |
   | v09 sat4 | 216 of 327 (66 %) | 22.4 | 7.6 | 60.7 / 60.2 | 28.6 / 28.3 |
   | v01 sat4 | 132 of 324 (41 %) | 17.1 | 8.1 | 64.7 / 64.3 | 29.8 / 29.2 |
   | v04 sat4 | 52 of 323 (16 %) | 15.5 | 7.7 | 62.3 / 61.2 | 28.7 / 28.3 |
   | v01 post-restart | 316 of 540 (59 %) | 21.4 | 6.9 | 48.0 / 46.3 | 26.8 / 26.2 |
   | v05 post-restart | 394 of 625 (63 %) | 21.1 | 6.8 | 48.1 / 47.4 | 26.7 / 26.5 |

   Without a job, `finish` costs 6.7-8.1 µs/tx on every validator in every loaded window, on slow and fast nodes alike
   (the other nodes not listed agree). The node-level spread comes from the share of outputs overlapped and from how
   hard they are hit (21-23 µs/tx when jobs run in pairs, item 5). Root and EVM move 0.2-2 µs/tx.
3. **The slow node-windows are exactly the S7 node-windows, and their arrivals are phase-locked to execute starts.**
   A6 stages.md (per-node p50): S7 > 0 only for v09 at 600 × 4 (1,914 ms), v01 / v03 / v05 prekill (10,745 / 1,592 /
   12,798 ms) and v01 / v03 post-kill (32,604 / 22,736 ms); 0 on every other node-window. Arrivals within 50 ms after a
   task start: v01 prekill 261 of 441, v03 190 of 448, v05 265 of 434, v09 sat4 259 of 322; 0-23 on every other
   node-window. Of the aligned arrivals, 304 of 336 (v01, 17:34-17:56), 175 of 222 (v03) and 286 of 295 (v09 sat4)
   followed a logged S7 wait (logged only above 1 s). A full engine queue accounts for 0-1 of them. One cycle on v01:

   ```
   17:45:00.033017  persisted output            consensus_number=11759
   17:45:00.033138  waited for execution ...    number=11766 waited_ms=8244
   17:45:00.045204  output queued               consensus_number=11766 depth=7      <- job starts
   17:45:00.047545  output execution task finished consensus_number=11759            <- 11760 starts executing
   17:45:00.120595  signers recovered           consensus_number=11766 txs=5587 recover_ms=75
   ```

   The job covered the first 73 ms of 11760's execute.
4. **The onset is the minute S7 engages, not a queue depth.** Per minute, `finish` µs/tx: v01 11.0 and 9.5 at
   17:38-17:39 (v02 11.1 and 10.6); S7 lines 9, then 38 at 17:40-17:41; `finish` 15.8, then 18.1. v03 stays at
   10.2-11.3 through 17:42; S7 lines 1, 13, 25 at 17:43-17:45; `finish` 15.3, 17.3, 18.8. v09 at 600 × 4: 4.7 at 16:56;
   S7 10, then 50 at 16:57-16:58; `finish` 17.1, then 19.1. Queue depth does not predict it (A4n f2.json buckets): v09
   was slow at 600 × 4 with depth p50 2 (max 4, never at 8); v02, v06, v07 and v09 were normal at depth p50 6-7 at
   17:45; v03 was still slow at 18:10 with depth p50 3 (`finish` 17.4), because S7 (post-kill p50 22.7 s) held its
   outputs upstream of the engine queue.
5. **The job's own slowdown comes from jobs running in pairs.** When one executed block clears several leaders' floors,
   the subscriber releases several outputs together (v01 17:45:05.684 / .700, outputs 11768 / 11769, `recover_ms` 239 /
   219 for 10,469 / 10,182 txs). Jobs that overlapped another job: v01 prekill 226 of 441, v03 151 of 448, v05 228 of
   434, v09 sat4 177 of 322, v05 post-restart 395 of 633; 0-8 on the other node-windows. On those nodes a job costs the
   same whether or not it overlaps an execute (12.6-13.5 µs/tx either way), so the job's slowdown is two jobs splitting
   one pool. That only adds to item 2: a pair keeps the pool busy twice as long.
6. **Size of the penalty.** Node-level `finish` minus that node's non-overlapped `finish`, prekill: v01 11.1, v03 10.1,
   v05 10.7 µs/tx; the other validators 3.5-4.7; obs11 3.0. sat4: v09 10.9, other validators 1.0-4.4, obs11 0.4. The prekill task gap
   between the slow three and the rest (294.9-297.9 vs 284.4-288.9 µs/tx) is this `finish` difference (6-7 µs/tx)
   plus the 1-3 µs/tx of evm and root.

## Mechanism

Lines are at 067639def in telcoin-network-bench5, reth v1.11.3 (d6324d6) and rayon-core 1.13.0.

1. **One pool, three users.** `crates/telcoin-network-cli/src/node.rs:233-244` builds the global rayon pool with
   `available_parallelism − 2` threads: 6 on a c3-highcpu-8. Under load three things use it:
   - the E4 job. `ExecutorEngine::enqueue` (`crates/engine/src/lib.rs:247-254`) calls `RecoveryHandle::spawn`
     (`crates/engine/src/recovery.rs:39-54`), one tokio blocking task per arriving non-empty output, which runs
     `RethEnv::recover_output_signers` (`crates/tn-reth/src/env/execution.rs:206-232`: `par_iter` over batches, then
     `recover_batch_signers` `par_iter` over transactions, `:816-835`). One job is about 13 µs/tx of wall time across all
     6 threads, about 80 ms for a 6 k-transaction output.
   - `finish`, on the execute thread, once per block (15-40 blocks per output). `build_recovered_block`
     (`execution.rs:328-363`) calls reth `BasicBlockBuilder::finish` (`crates/evm/evm/src/execute.rs:477-490`). That
     calls `hashed_post_state` → `HashedPostState::from_bundle_state`, an `into_par_iter`
     (`crates/trie/common/src/hashed_state.rs:48-69`; the `rayon` feature comes from `crates/trie/trie/Cargo.toml:21`).
     Then comes the `rayon::join` of the two `into_sorted` calls (`execution.rs:352-353`). The state root
     (`output_overlay.rs:103-121`, reth `StateRoot`) and the transaction loop run on the execute thread without rayon,
     which is why root and EVM barely move.
   - the batch validator: `decode_transactions` runs `recover_and_validate` in a `par_iter` for every peer batch
     (`crates/batch-validator/src/validator.rs:164-173`). The observer's lower non-overlapped `finish` (5.5-5.8 vs
     6.7-8.1 µs/tx) fits it doing less of this, but that is not verified.
2. **The execute thread has no priority on that pool.** It is not a rayon worker, so its `par_iter` and `join` are
   injected into the registry's queue. A worker looks for work in its own deque first, then steals from other workers,
   and only then takes injected jobs (`rayon-core-1.13.0/src/registry.rs:833-842`). While a recovery job still has split
   work in any worker's deque, each `finish` call waits for the rest of the job. Measured: +8-15 µs/tx on an overlapped
   output, i.e. 50-90 ms per 6 k-transaction output, the same order as one job (80-120 ms).
3. **When the job starts decides whether it overlaps an execute.** The job starts when the output is queued.
   - With S7 = 0 an output arrives when consensus commits it, at a random point of the running task. Execute is about
     30 % of a task and persist (IO-bound) about 69 %, so 5-46 % of outputs are overlapped at saturation.
   - With S7 > 0, `wait_for_leader_execution` (`crates/consensus/executor/src/subscriber.rs:1163-1190`, called at
     `:1023`) waits until `recent_blocks` reaches the leader's execution block. That watch advances when an output is
     persisted. The engine then picks up the task result (`lib.rs:360`) and spawns the next execute task at the top of
     the loop (`:308-310`) while the released output is being queued (`:326-349`). The job therefore starts within about
     15 ms of the next execute and covers its first blocks. The wait floor is a running maximum (`next_wait_floor`,
     `subscriber.rs:1303`), so one persisted output often clears several floors at once and the jobs come in pairs.
4. **The feedback loop.** S7 engages when a node's execution trails the leaders' by more than about one commit
   latency (ts 1.9-2.9 s under load, A6). Under 600 × 16 the fastest executors led almost nothing (v04 and v08 0, v10 10
   of 459 prekill leader rounds, triage (d)), so most leaders were middle-tier nodes, with queue_wait 6.0-6.4 s at 17:40
   (A4n buckets). v01 and v05 were at 8.9-9.0 s. Once S7 is
   engaged, the node pays about 10-11 µs/tx (≈ 3.5 % of its task). That is more than its margin against the commit
   rate, which follows the leaders' execution, so the node falls further behind and S7 stays on. Each node is stable in
   either state, and the slow state lasted until the load ended. Which node enters it is not fixed (v09 at 600 × 4,
   v01/v03/v05 at 600 × 16).
5. **Why it is new in bench 5.** Before E4, recovery ran inline on the execute thread, so there was nothing to
   overlap. The S7 wait arrived with `f1-commit-lag` (the fork check moved into the subscriber). The phase-locking needs
   both.

## Alternatives weighed

- **(a) Rayon contention from E4: in, with a corrected mechanism.** It is not "up to 8 queued jobs competing". At
  saturation one job starts per arrival (0.56 per second, 80-120 ms each), so 0-2 run at once. The 8-job burst happens
  only on catch-up (the note at `crates/engine/src/payload_builder.rs:66-70`; v05 post-restart). What matters is when
  the job runs, and S7 makes it run during an execute. Queue depth is at best a proxy (counterexamples in Evidence 4).
  600 × 4 shows the same within-node split on every validator (overlapped 15.1-22.4 vs not 7.5-8.1 µs/tx; obs11 10.9 on
  16 outputs vs 6.6), and its one slow node, v09, was its one S7 node.
- **(b) Memory or cache pressure from the queued outputs: out.** Node-wide pressure would slow non-overlapped outputs
  too. On v01/v03/v05 those cost 7.1 / 7.1 / 8.0 µs/tx against 6.7-7.1 elsewhere, and the root, the most memory-bound
  phase, moves 1-3 %. The RSS growth (5.2-6.1 GB prekill, 6.3-8.5 GB post-restart) stays a separate NEEDS DATA item
  (triage, bench-4 watch items).
- **(c) The node's own RPC and txpool load: out.** The same within-node argument applies. Generator 01 also submitted
  the least (694,754 vs 898,986-1,170,590, triage (a)), because the lag kept its senders window-blocked.
- **(d) Hardware variance: out.** The slow set changed between 600 × 4 and 600 × 16 on the same VMs (v09, then
  v01/v03/v05). v01 and v03 matched v02's `finish` before S7 engaged (17:38-17:42), and non-overlapped `finish` is
  equal across nodes. The CPU platform per node is still not recorded (A4n bench-6 probe list).
- **(e) `finish` growing with the overlay: out as a per-node difference.** Every node executes the same outputs
  (6,006-6,042 txs per output in prekill), and non-overlapped `finish` is equal across nodes. `finish` per transaction
  does grow with output size across the whole fleet (4.4-4.9 µs/tx at light load, 6.6-8.1 non-overlapped at
  saturation: the sorts and the overlay compaction). That is a separate cost and the same on every node.

## Proposal

None of the options changes a block. The same function recovers the same bytes in the same order (`par_iter` +
`collect` keeps order) and drops the same transactions, so block hashes, roots, receipts and gas are unchanged.

- **(A) A dedicated pool for signer recovery.** Build one `rayon::ThreadPool` (`tn-recover-{i}`) at engine start and
  run `recover_output_signers` inside `pool.install(..)` from the E4 job and the inline fallback. The execute thread's
  injected work then finds idle global workers. The two pools share the 8 vCPUs through the OS scheduler, which
  time-slices instead of making `finish` queue behind the whole job. Recovering only the next output does not help on
  its own: starting N+1's job when N starts executing is exactly the overlap measured here.
- **(B) A separate pool for execution.** This is (A) from the other side, and larger: reth reaches the global pool
  from inside `finish` through `into_par_iter`, so the whole block build would need an `install`, and the batch
  validator and the rest of reth would stay on the global pool. (A) is the smaller form of it.
- **(C) Recover at most 2 outputs ahead.** It bounds memory, not timing. On an S7 node the engine queue is already
  short and every arrival is still aligned. It does not remove the overlap.
- **(D) Revert E4.** E4 takes 12-13 µs/tx off the execute thread (light-load `recover_wait` 11.7-13.1 µs/tx; 0.0-0.6 at
  saturation). The contention it adds is 3.0-4.7 µs/tx of `finish` on non-S7 nodes, 10-11 on S7 nodes, plus 1-3 of evm
  and root. Net: about +8 µs/tx on most nodes and about 0 on the S7 nodes. A revert removes the loop at a cost of about
  8 µs/tx on most nodes; (A) removes the loop and keeps the saving. Keep (D) as the fallback if (A) fails its test.
- **(E) Bound in-flight transactions at the node (A6 lever 1).** Below the ceiling this removes the trigger (no deep
  queue, no S7), and it is the right latency fix. At saturation some node is always the slowest, so with (E) alone
  the loop is still there. It complements (A) but does not replace it.

**Recommendation for bench 6: (A)**, with `k = max(1, (available_parallelism − 2) / 2)` threads, 3 on a c3-highcpu-8,
so that the execute thread, the global pool and recovery do not oversubscribe 4 cores badly. Expected effects:
- `finish` falls to the non-overlapped 6.7-8.1 µs/tx on every node, whatever S7 does, so the task drops 3.5-11 µs/tx
  (median 288.6 → about 284; the slow nodes' 297 → about 286), and the bistable state goes away.
- With 3 threads a job takes about twice as long (about 25 µs/tx, 150 ms for a 6 k-transaction output). That is still
  far below the 1.8 s between outputs, so `recover_wait` stays near 0 under load.
- At light load the execute task waits for its own job. `recover_wait` rises from about 12 to about 25 µs/tx (6 → 12 ms
  for a 479-transaction output), which does not matter against a 1.5 s seen.
- An optional refinement: lower the recovery threads' OS priority in the pool's `start_handler`, so the scheduler
  prefers the execute thread when both want a core (only if `libc` is already a dependency of the crate).
- Moving the batch validator's recovery to the same pool is a follow-up, to try only if bench 6 still shows validators'
  non-overlapped `finish` above the observer's. It sits on the batch-ack path, so it needs its own latency check.

## Test plan

- **Criterion (engine or tn-reth bench, `tn-add-benchmark` pattern).** Build a 6 k-transaction, 20-block output
  through `build_block_from_recovered_payload` while N ∈ {0, 1, 2} recovery jobs for other 6 k-transaction outputs start
  with it. Run it once with the jobs on the global pool, as today, which must reproduce +8-15 µs/tx of `finish` at
  N = 1 and serves as the check that the bench sees the effect. Run it again with the jobs on the dedicated pool. Pass:
  `finish` per transaction at N = 1 and 2 within 15 % of N = 0, and evm + root within 5 %.
- **Differential.** Re-run the E4 differential tests (bytes path vs pre-recovered: same block hashes, state roots,
  receipts roots, gas) and the recovery-fallback test with recovery on the dedicated pool, plus `recover_drop_props.rs`.
- **e2e.** Run 4 validators under a steady transaction load, with one slowed through the existing hook
  `tn_types::test_hooks::execution_delay()` (`crates/engine/src/lib.rs:180-183`) until its subscriber logs `waited for
  execution before assembling the output`. Assert from `output executed` that mean `finish_ms / txs` on the slowed node
  stays within 20 % of the other three, and that on that node outputs released by an S7 wait cost no more than 1.2 ×
  the rest. On today's build the slowed node should fail the first assertion (check this once by hand, so the test
  is known to detect the effect).

## What the next benchmark run reads

- Per output: overlapped vs not-overlapped `finish` µs/tx (re-run `overlap.py` on the new logs). Expect them within
  1-2 µs/tx of each other on every node (today 15-23 vs 6.7-8.1).
- Node-level `finish` µs/tx at saturation: spread ≤ 1.5 µs/tx across validators, with no relation to queue_wait or S7
  (today 10.2-18.7).
- `signers recovered` µs/tx: about twice today's 13 (fewer threads), and no longer higher on S7 nodes.
- S7 (`waited_ms`): p95 < 2 s on every validator in the load windows (today block-weighted p95 16.9 s prekill and
  31.8 s post-kill, A6).
- Epoch records closed under load: ≥ 9 of 10 signers (today 7 of 10 at both loaded closes).
- `tn_primary_votes_refused_execution_behind_total`: no node far above the rest (today v01 14,802 against v08 588).
- The chaos node: net catch-up ≥ 8 outputs/min under load (today about 7). Its post-restart penalty was 10.1 µs/tx of a
  242 µs/tx task, so (A) buys about 4 % of replay rate. Catching up fully under load still depends on the persist work
  (`bench5-f2-execution-ceiling.md`, investigation 2).
- If bench 6 also ships (E), run one 600 × 16 arm without it, so that (A) is measured at saturation.
