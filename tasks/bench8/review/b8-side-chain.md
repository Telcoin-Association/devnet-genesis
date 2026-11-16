# RVB-side: review of the bench 8 side chain (b8/side, 91a15e223..d7d9920eb)

Worktree `/home/drtnarg/coding/telcoin/tn-b8-bench2`, six commits. Read-only review, no cargo run. Line numbers are at d7d9920eb.

## Verdict: approve with follow-ups

No Critical, no High. 1 Medium (a field's meaning is described too narrowly, in `node-fields.md` and in a metric doc; the code is right). 9 Lows: test gaps, one immaterial cost inside a measured span, one redundancy.
With every parameter at its default, none of the six commits changes a decision, a send, its order, what is stored or an error returned. What each adds on a hot path is listed under question 1 for that commit.

## Per commit

### fbea152d4: exec tip and deficit on `vote path timing`
1. No behaviour change. `vote()` (handler.rs:950-958) reads `header.latest_execution_block().number` and `consensus_bus.latest_execution_block_num_hash()` (a `watch` read lock, `back().cloned()` of one `SealedHeader`, released at once) before `VoteTiming::new()`. `observe_vote` (handler.rs:978-986) takes one `recent_blocks().borrow()` inside a block that ends before the metrics and the log. It is synchronous and runs after `vote_request` returned, so after the author lock is released and with no await held. Same watch as the arrival read, so the two reads agree. The response goes back a few µs later; nothing else differs.
2. Values are right. `outputs_to_reach` (recent_blocks.rs:129-160), walked case by case. Named below or equal to the tip: `(0,true)`. Above the tip and reached: walks newest-first, stops at the first entry ≤ tip, counts entries < named plus 1 for the oldest entry ≥ named. Entries executed after the block was reached do not add. Ring shorter than the gap: the walk never stops, so the result is a lower bound (documented). Never arrives: every entry > tip, `false`. The ring holds one entry per output that produced a block (`push_latest`, recent_blocks.rs:40-56) and is monotonic in block number, so `take_while` is sound. One wording problem: see M1. Empty ring at startup logs tip 0 (L4).
3. Cost. Two watch read locks and a walk bounded by the outputs executed since arrival, per request. The writer (engine `send_modify`) takes the write lock once per output. No allocation per transaction. The line grows by about 150 B (`exec_named=… exec_tip_arrival=… exec_tip_answer=… exec_deficit_outputs=… exec_deficit_open=false superseded_by_round=0 superseded_after_ms=0`, with 42f9bdb32). At about 25 × 9/10 ≈ 22 requests/s per node that is about 3.3 KB/s per node at DEBUG, the largest growth in the chain. The histogram costs one record per request.
4. Tests pin values: `vote_path_timing_line_carries_exec_deficit` (network_tests.rs, the asserts at :7736-:7763) gives exact strings for open (3/0/1/1/true), reached (4/1/4/3/false) and held (2/4/4/0/false), plus the histogram samples `[3,0]` and `[1]`. The recorder test pins the `le="4"` bucket. Gaps: L1, L2.
5. Rules: no unwrap/expect outside tests; `///` on `ExecArrival`, `outputs_to_reach`, `record_exec_deficit` and the buckets; no new dependency; message ends `Topic: bench8-obs`, no attribution.

### 42f9bdb32: what superseded a vote request
1. The decision is identical. Base: `match newest.get(author).copied() { Some((e,r)) if header.epoch()==e && header.round()<r => Err(Superseded), _ => { if record { insert(author,(epoch,round)) } Ok(()) } }`. Tip (handler.rs:1420-1452): same guard, same strict `<`, same epoch equality, same `record` condition at the same three call sites (:1094 `in_window`, :1109 and :1174 `false`). The same `(epoch, round)` is written. Only the third tuple element is new. For a repeat of the stored `(epoch, round)` the stored `arrival` is kept (`Some((e,r,a)) if (e,r)==(header.epoch(),header.round()) => a`); any other write takes `timing.started`. A repeat therefore rewrites the same `(epoch, round)` as before, and the mark is raised exactly when it was. The map is touched nowhere else (`grep`: :222, :272, :1421 only). `SupersededRequest` is built only at :1428, so `outcome=superseded` always has `timing.superseded` set.
2. `superseded_by_round` is the mark's round at the refusal, which can be more than one above this request's round (documented). `superseded_after_ms` = `mark_arrival.saturating_duration_since(started)` (:2465), so a mark that arrived first gives 0. The arrival is the first *recorded* request of that round (L8).
3. Cost: one 3-tuple store and one `Option` write under a parking_lot mutex already taken. No await, no allocation.
4. Tests: round 2 superseded by round 3 → `superseded_by_round=3`, `gap ≤ after ≤ total_ms`; an answered request → `0 0`; a stale round-1 request → `3 0`. Not tested: the repeat keeps the first arrival (L3).
5. Rules OK. `NewestVoteRequest` and `VoteTiming::superseded` are documented.

### 5a81a11f5: test only
Gap 300 → 50 ms (`VOTE_EXECUTION_WAIT > gap*10`), and the order check now `expect`s both positions. The same `Option<usize>` comparison flaw remains in fbea152d4's test (L1). Rules OK.

### 48991d94c: `leader schedule updated`
1. `LeaderSwapTable::new` returns the same table. The `good_nodes`/`bad_nodes` computation is untouched (:66-176); `Self { round, good_nodes, bad_nodes }` is built from the same values and returned after the log. The two removed `.expect()` calls guarded nothing. They were arguments of `debug!`, so they were evaluated only with DEBUG on `primary::leader_schedule`, and both looked up nodes drawn from `reputation_scores.authorities_by_score_desc()`, which comes from `scores_per_authority`, so the lookup could not fail. The pre-existing `assert!`s (:74, :169) stay. Call sites: bullshark.rs:409 (only `if reputation_scores.final_of_schedule`) and `from_store` (leader_schedule.rs:284, the latest final scores at restart). The two other calls are `#[cfg(test)]`.
2. `scores_per_authority` is a `BTreeMap<AuthorityIdentifier,u64>` (types/src/primary/reputation.rs:12), so `scores` is in id order. `good`/`bad` are sorted in `render_sorted_ids`. The list is bounded at 10, then `,+N`. `round` is `Round` = **u32** (types/src/primary/mod.rs:231), not u64.
3. One line per 60-leader-round window; three DEBUG lines are removed. Cost is negligible.
4. Tests pin rendered `scores`, `good`, `bad`, empty lists and `+2` overflow. The emitted line (epoch, round, `final_of_schedule`, field order) is not captured (L5).
5. Rules OK; `let _ = write!` into a String cannot fail.

### 94ebb2e50: `store_bytes` on `persisted output`
1. Not Critical. What I verified:
   - The handle is the same environment. `RethDb = Arc<RethDbEnv>` (env/database.rs:38) and `RethDbEnv = tn_lmdb_reth::TnLmdbEnv` (:34), so `provider_factory.db_ref().clone()` (env/mod.rs:220) is a refcount bump, not a second opening.
   - Drop order is unchanged. `store_env` sits in `RethEnvInner` next to `blockchain_provider`, which already holds the factory's clone. Both drop in the same struct drop, so the extra clone can never outlive a reference the struct already held. No `strong_count`/`try_unwrap` on the store handle exists in tn-reth, node or engine (grep).
   - `stat()` runs on the committing thread right after `provider_rw.commit()?` (execution.rs:597-604), before announce. `Env::stat()` (tn-lmdb/src/env.rs:2092) = `self.inner.current().meta` → `Arc::clone(&self.current.read())` (:580): one RwLock read of the snapshot pointer. It takes no writer slot, does no I/O or sync and walks no tree. The commit's own write lock is already released. The brief strong `Arc<Snapshot>` pins the current snapshot, which is never reclaimable anyway.
   It cannot block on the writer or a sync. Behaviour is unchanged except announce comes about 100 ns later.
2. Value = `page_count(u32) × page_size(u32)` as u64 (no overflow): the newest commit's high-water mark, free pages included. `None` on MDBX, so the key is absent (tracing skips a `None`).
3. One lock read per persist (~1.2/s), evaluated even when the line is disabled. Negligible.
4. Tested only as `> 0` and last on the line, and only in d7d9920eb (L6).
5. Rules OK; both cfg arms are documented.

### d7d9920eb: `cpu_ms`, `outputs_behind`
1. `execute_consensus_output_with_signers` is a synchronous fn run inside `spawn_blocking_task`'s closure (lib.rs:187), so both schedstat readings are of the same OS thread: a sync call cannot change threads. Signer recovery and any pool threads are not counted (documented). One cost sits inside a measured span: L7. The atomic stores are `Relaxed`, on the engine loop.
2. `outputs_behind`: every mutation of `queued` is covered: push at lib.rs:265 (store :266) and pop in `take_next_queued` at :172 (store :174). No `clear`/`drain`/`retain`/`truncate` exists. The stores at :363 and :384 are redundant (L9). The load (:217) happens as the task logs, before `tx.send`. Outputs still in the channel are not counted (documented). `cpu_ms` = first schedstat field (`sum_exec_runtime`, ns), each end lagging up to a tick. It is `0 0 0` without `CONFIG_SCHED_INFO`, which reads like a real 0. The key is absent when the file is missing.
3. Two `read_to_string` of procfs per output (open/read/close plus two small Strings), ~1.2/s. Negligible.
4. `outputs_behind` is pinned only at 0, `cpu_ms` only `≤ execute_ms + 25`, `store_bytes` only `> 0` (L6).
5. Rules OK; `thread_cpu_time` and `queue_depth` are documented; std only.

## Findings

### Medium
**M1. `exec_deficit_open` and the `open="true"` histogram mean "not held at the answer", not "the wait ended without the block".** handler.rs:986 `let exec_deficit_open = !reached;`. `reached` is false whenever named > arrival tip and no ring entry ≥ named exists at the answer. That holds for any outcome, including requests refused at once with no wait (superseded on arrival, invalid header, wrong epoch, timeout before the wait). Their `exec_deficit_outputs` then counts the outputs executed between arrival and answer, usually 0, and they land in `open="true"` bucket 0. The metrics.rs doc ("the outputs executed during a wait that ended without the block") and node-fields say otherwise. An analysis that reads `open=true` as "waited and missed" mixes in no-wait refusals. Smallest fix: correct node-fields (below) and the metrics.rs doc. In the analysis, split by `outcome` and `prelock_wait_ms + exec_wait_ms > 0`. No code change is needed for the run.

### Low
- L1. network_tests.rs:7742 `assert!(open.find(" total_ms=") < open.find(" exec_named="))` passes when `total_ms` is missing (`None < Some`): the flaw 5a81a11f5 fixed at :7852-7854 but not here. Fix: `expect` both positions.
- L2. No test of `outputs_to_reach` with entries above `named` (executed after reaching it) or with a ring shorter than the gap. Fix: a direct `RecentBlocks::new(4)` unit test.
- L3. No test that a repeat request of the newest `(epoch, round)` keeps the first arrival, the only new write logic in 42f9bdb32.
- L4. With an empty ring (startup) `exec_tip_arrival`/`exec_tip_answer` log 0 (`unwrap_or_else(Default::default)`, recent_blocks.rs:74), which looks like block 0. The deficit then counts the whole ring. Startup only.
- L5. The `leader schedule updated` line itself (epoch, round, `final_of_schedule`, field order) is not captured by any test; only the render helpers are.
- L6. Engine test: `outputs_behind` pinned only at 0; `cpu_ms` only bounded above; `store_bytes` only `> 0`. `expect("cpu_ms")` fails on a host without procfs (macOS dev box).
- L7. payload_builder.rs: `execute_cpu_start = thread_cpu_time()` comes after `execute_start = Instant::now()`, so `execute_ms` now includes one procfs open/read/close (~10-30 µs per output). This is immaterial against execute_ms in the hundreds of ms. Fix if wanted: read the CPU clock before `execute_start`.
- L8. `superseded_after_ms` times the first *recorded* request of the mark's round. A first request refused before recording (outside the vote window, or from a peer that is not its author) is not the one timed. Edge case; document it.
- L9. lib.rs:363 and :384 `queue_depth.store` are redundant with :174/:266 but harmless.

## Corrections to `tasks/bench8/node-fields.md`
- `exec_deficit_open`: "true when the wait ended without the block" → "true when the named block was above the arrival tip and still not in the ring at the answer, for any outcome, including requests refused on arrival without a wait (`exec_deficit_outputs` is then the outputs executed between arrival and answer, often 0)".
- `exec_deficit_outputs`: "a lower bound when `exec_deficit_open=true`" → add "and 0 for an open request refused before any output executed".
- Histogram paragraph: "one sample per request" → add "`open=\"true\"` includes requests refused without a wait; split by `outcome` in analysis".
- `exec_tip_arrival` / `exec_tip_answer`: add "0 while the ring is empty (startup)".
- `superseded_after_ms`: "to the FIRST arrival of that mark round's request" → "to the first arrival of that round's request that raised the mark (from its author, inside the vote window)".
- `leader schedule updated`: "`round` (u64: …)" → "`round` (u32, `Round`: …)".
- `cpu_ms`: add "the start reading lies inside `execute_ms`'s span (one procfs read, ~10-30 µs)".
- `store_bytes`: "from the node's own tn-lmdb handle" → "from a clone of the `Arc<TnLmdbEnv>` the provider factory holds (same environment, no second opening); one RwLock read of the current snapshot pointer, no writer slot, no I/O".
