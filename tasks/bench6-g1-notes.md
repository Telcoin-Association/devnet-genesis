# Bench 6 — G1 notes (what the user confirms after W1 and the one-VM probe)

The orchestrator collects every decision for the G1 gate here as hand-backs arrive. Sources are cited; nothing here is decided.

## From I-4 (design answers; `benchmark/private/bench6-prep/I-4/{answers,unit-specs,issue-comment-drafts}.md`)

### D1. Which form of the proposer fix (#1804 design D) ships
- Finding (high confidence; arithmetic on the rule + a ten-node model, `answers.md` §1): with the rule applied to every header, the
  parents' named blocks are earlier choices of the same rule, not tips, so the fleet's highest named block can only rise through the
  floor. Every proposer settles exactly 8 ring entries below its own tip at every load: ≈ 14 s stale at bench-5 saturation, ≈ 5.6 s
  at light load. It still fixes the starvation while the fast nodes lead the 7th member by ≤ 8 outputs; the issue's field
  "`exec_tip - exec_block` = 0 at idle, `floor` is rare" fails by construction.
- Options: (a) accept the floor (rule as designed); (b) own tip by default, the quorum rule for K rounds (doubling) after an own
  header was cancelled uncertified, time-based return to the tip (I-4's recommendation; in step the lag is 0 and the parents' values
  are real tips); (c) carry the tip in the header (wire + fork-gated change; not for bench 6); (d) a smaller N.
- Orchestrator action taken (reversible, no decision pre-empted): a twelfth switch `quorum_exec_block_starved_rounds` (int, default 0)
  is being added so that BOTH (a) (`0`) and (b) (`K > 0`, arm value 4) are built behind `quorum_exec_block` and run 1 can measure
  them. Which one the V arm and the headline use is the user's call here and at G3.
- Also for upstream (G4): is a canary up to N outputs stale acceptable (design question E3)?

### D2. `epoch_record_state_check` on whenever D is on
- With D, the voter check and the subscriber fork check both read the named (older) block, so neither stays immediate; a member that
  reaches the epoch close late skips its `final_state` comparison today (`close_epoch.rs:416-422`). The U5 check closes that window.
- The plan's default was "`epoch_record_state_check` off in the image". I-4 recommends: on in every arm where `quorum_exec_block` is on.

### Facts recorded (no decision)
- Q6: no code waits for 7 of 10 at the close; the 7 is the new epoch's first-certificate quorum, correct and not tunable.
  Tracker-drain changes no timing: it removes the `Failed to track` errors and adds gauges and the `final_state` halt.
- Q7: no fetch cap and no rate cap on rejoin replay; the bounded `consensus_output` queue and the engine queue (cap 8) meter it.
  Bench 5 was execution-bound and never hit a fetch limit (state-sync not read: fetch side inferred from logs).
- Q5: overflowed task-tracking messages (and up to 1,000 still queued) escape `abort_all_tasks`; such tasks end only when the manager
  drops at `run_epoch`'s return, after `finish_epoch` sealed the pack. A late `Votes` write is harmless next epoch, but a restart then
  logs a misleading "binary without this check" error. Blocking tasks are never stopped.
- Collector retry: resend every 250 ms up to 6 times, then 0/0.1/0.5/1/2/5/10 s backoff until a newer own header cancels it.
  Hazard for V: `network/message.rs:294` ends in a catch-all `InvalidHeader(_) => Error`, so a new `SupersededRequest` would silently
  become a fatal refusal unless added to the recoverable arm; U2 therefore also owns `network/message.rs` (that arm) and
  `error/network.rs` (the exhaustive penalty match; penalty `None`).

## From U8
- Optional: a 50 µs first bucket for the sub-ms histogram set would change five existing series; left out. Per-tx engine costs come
  from `_sum / executed_transactions_total`, not from quantiles.

## Pending: I-1, I-2, I-3, I-5, I-6, the GCE probe, the archive verify (prune question), the boot image pin (H0)

## From I-3 (ceiling recut; `benchmark/private/bench6-prep/I-3/{verdict.md,report-corrections.md,parallel-root-note.md}`; section 3b pending U4b)

### Facts
- Real phases (from the blasters' own `run.phases`): 600 × 4 (16:57:31-17:02:55) 3,868.5 tx/s chain, engine busy 972 ms/s, task
  250.4 µs/tx (execute 108.7, persist 142.4, commit 120.0); 600 × 16 (17:41:01 to the kill 17:54:44) 3,466.2 tx/s, busy 999, task
  289.2 (execute 89.2, persist 199.5, commit 178.6). Both engine-bound. Capacity at busy 1: 3,993 vs 3,458 tx/s.
- **The commit cost drifts with elapsed load, not with the window**: +0.031 s per output per minute of load in both windows
  (0.37 → 0.52 s inside 600 × 4; 0.88 → 1.27 s inside 600 × 16; fit inside 600 × 16: 0.691 s + 0.0285 s per 1k tx + 0.0306 s/min,
  r² 0.963). At the same moment larger outputs commit cheaper per tx. 600 × 4 ran 40 min earlier, so bench 5 cannot say which window
  has more capacity.
- E5's share is not separable from the runs (bench 4's snapshot has no stage histograms): execute fell 167.7 → 89.2 µs/tx; E4 = 12-13;
  E1 + E5 + the clone drop = 65-72.
- Recovery overlap (v09, per output): `finish` 22.1 vs 7.8 µs/tx at 600 × 4, 16.3 vs 6.7 at 600 × 16 when another output's recovery
  job overlapped; root and evm unchanged; dose-response with the overlapped share. Supports the recovery pool (#1805).
- Memory: no reclaim anywhere (PSI memory 0.00 on every sample; GCP used ≤ 36 % of 16 GiB; 4.7-5.6 MB read from disk per process over
  the run). `mdbx.dat`'s share of rss_file (3.0-3.2 GiB) is not measurable (sampler `cache_bytes` empty) — the bench-6 persist sampler
  (H4: fincore) fixes that. anon grew 1.0-1.7 GiB per node under load and was not returned (retention vs leak not separable).
- v09's three not-found leader rounds at 600 × 4: its own proposer sat in the #934 durability barrier (`header stored and sent`
  `persist_ms` 1,639 / 5,294 / 2,074 ms; all 13 waits ≥ 500 ms fall in 16:57:47-16:59:24). No issue records the barrier costing
  leader rounds.

### Decisions
- D3. **Arm design for run 1**: the per-output commit drifts ≈ +0.031 s/min of load, so any two arms compared must be at the same
  database age. The planned A0 … A0′ sequence bounds drift only end to end. Options: keep the plan (A-B-A + equal M16 windows) and
  correct every arm with the fitted drift; or alternate short blocks; or evict/restore between arms. Also: is the drift itself the
  large-folio writeback growing with database size (then P1 should flatten it — the first thing arm 1 must show)?
- D4. Recovery pool only (as planned), or should the U4b Criterion bench also try a separate pool for root/finish?
- D5. File the durability-barrier stall (leader rounds lost while the proposer waits for the epoch-DB commit) as an upstream issue
  after the run? A read-only zgrep of `persist_ms ≥ 500` over all 11 bench-5 logs would size it (orchestrator will run it with I-3's resume).
- D6. Split bench 4's execute offline from its per-block dump timestamps (≈ 49 GB of logs per node)? Orchestrator's view: no — low value.

### Report corrections
- I-3 lists ten corrections to the bench-5 report (`I-3/report-corrections.md`); they go into the report in a second pass (I-6b)
  together with whatever I-2 finds, before the G1 review of the corrected report and the re-bundle.

## From I-5 (pipelined persist design; `benchmark/private/bench6-prep/I-5/{design.md,open-questions.md}`)

### Facts
- Design is executable: two slots (`building`, `committing`) + one parking spot (`built`), depth 1; N+1 builds on N's in-memory tip
  with a scope seeded from N's trie runs and every state root over ONE read snapshot pinned before persist(N) is spawned (the
  riskiest invariant: without the pin, N's deltas are layered over a DB that already holds them and the emitted trie updates can
  differ even when the root matches). Announce and finalize stay after the commit, in consensus order. A closing output is a barrier
  inside the engine (`run_epoch.rs` untouched). First error wins: wait for the other slot, roll every unpersisted block back, stop the node.
- Reth's own engine persists in the background through the same `remove_persisted_blocks` / `ConsistentProvider` paths.
- The ×1.41 gain is a ceiling: if persist slows 20 % when it overlaps a build, the gain is ≈ ×1.2.
- I-5's opinion: go for implementation (≈ 2 days of unit work); the schedule risk is the e2e lane (4-5 h) plus review; keep U12 last
  in the cherry-pick order and enable the arm only if gates 1-5 (design.md §6.5) are green by the cutoff.
- Orchestrator settled the three ownership gaps: U0c adds `OutputBuildScope::seeded(overlay, tip)` in `execution.rs` and makes the
  module line `pub mod persister;`; U12a owns `crates/engine/src/error.rs` (one `PipelineInvariant` variant); ST-U12a owns the
  `mod persist_pipeline;` line in `crates/engine/tests/it/main.rs`.

### Decisions
- D7. Cutoff (date and hour) for the pipelined-persist go/no-go gates. Orchestrator's proposal: the moment the integrated branch
  enters its W3 gates; if any of the five gates is not green then, the image ships without the key.
- D8. RPC `latest` can show up to two outputs that are not yet durable (today: one). Acceptable for the bench? For upstream?
- D9. `rpc_admission_backlog_outputs` 2 or 3 when pipelining is on (one more output is in flight).
- D10. Put #1808 (the #1790 restart-replay fix, approved, unattested upstream) into the image anyway? It only affects adiri builds; the
  bench image is a `faucet` build.
- D11. Carrying the read cache across outputs is left as a follow-up (the pipelined N+1 starts with trie runs only). OK?
- (G4) Does the `pipelined_persist` kill switch stay upstream for one release?

## From I-2 (generator and sealed transactions; `benchmark/private/bench6-prep/I-2/{verdict.md,h9-measurement-spec.md,sealed-keep-test-cases.md,issue-1807-evidence.md}`)

### Facts
- **No window was generator-bound.** Load 600 × 16: 2,232 of 2,400 generator-windows node-bound (in-flight within 3σ of 9,600), 118
  node-unavailable (gen 05 after the kill), 50 censored tail. 600 × 4: 342 node-bound, 18 censored. Light blasts: window-capped by
  design or too thin to tell. RPC accept p50 5-11 ms, p95 18-35 ms under load.
- **Resend reconciliation closes**: `submitted − accepted` = the gap-resend call count. 14,046 resend events, 235,073 calls; 39.5 %
  answered `already known`, 60.5 % (142,240) accepted as new because the node had no record. Exact landings ≥ 256 s: 150,028 (1.81 %;
  the sampled figure was 1.85 %). On gens 04/08/10, 37,683 `nonce too low` against 79,517 new resends: ≈ 47 % executed twice.
  validator-02 also logged 24,623 `nonce too high` skips in the preamble (not in bench 5's count).
- **The pool did drop accepted transactions**: 3,804 queued-pool evictions (v02 1,505 and v10 2,201 at 17:39:15, v04 98 at 17:41:00);
  those nodes began the load with the most stale queued entries left by blasts 2 and 3 (21,332 fleet-wide; nothing expires them).
  Queued peaked at 9,341 on v04 against reth's 10k default.
- **The 34,378 unlanded: ≥ 95 % lost, not late.** At 18:56 the queued pools still held 11,927 of them behind nonce holes; on seven
  generators they were submitted in the last 1-4 minutes, so the 300-s repair would have come after the senders stopped.
- **The "65" are sampled landings, not batches**: submitted in the 36 s before an epoch boundary, never skipped, landed 304-320 s
  later. At the boundaries 100 seal errors hit 22 digests; two batches that failed with `FailedToReport` (370 and 328 txs) were
  rebuilt with the same digest ≈ 85 times until the orphan re-pool ran. Which path lost them without a skip is unexplained.
- **Benches 3 and 4 had the cliff too** (share ≥ 256 s: 2.20 %, 0.87 %; bench 5's 600 × 4: 0.30 %). The land-p99 jump from 31 s to
  403 s is the tail crossing 1 %, not a new mechanism. The #1807 text is wrong where it says the 600 × 4 window ended before any
  300-s resend (corrected in the evidence draft).
- Unexplained: why each transaction was resent (no cause recorded), ≈ 9-10k of the unlanded, which transactions reth evicted, the
  node's configured queued limit.

### Decisions
- D12. **Pool hygiene between blasts** (harness): stale queued entries from earlier blasts plus 9,600 in flight per node leave almost
  no headroom under the queued limit, and run 1 puts ≈ 15 blasts on one deployment. Options: record `txpool_status` per node at
  every blast start (cheap; orchestrator adds it to the blast unit either way); refuse/wait when queued is above a threshold; a
  rolling restart between blasts of one arm (clears the pool, costs ≈ 10 min); raise the node's queued limit (changes the system
  under test). Orchestrator's proposal: record always, and require queued < 1,000 per node at an M16 start in run 1 (arm switches
  restart every node anyway; inside an arm the light blasts run first).
- D13. Judge `sealed-keep` on stalled-for-300-s senders and the exact ≥ 256 s landing count, not on land p99 (threshold effect).
- D14. **Epoch-boundary loss is an uncovered path** (the 65; same-digest rebuilds after `FailedToReport`). Not in the fix list.
  Bench 6 measures it (POOL arm has a boundary inside its M16); test case S6 goes to the sealed-tx e2e unit (ST-U6). A fix would be
  a new topic: decide after run 1.
- D15. Generator measurements beyond the design (I-2 spec): gap resends split by the node's answer, stalled-sender columns, a
  per-transaction unlanded export, a finer tail histogram. Orchestrator: take them (additive), in H9a if it read the spec in time,
  else H9b.

## From I-1 (persist trigger; `benchmark/private/bench6-prep/I-1/{verdict.md,probe-arms.md,run-i1.sh,u3-notes.md}`)

### Facts
- **Ranked trigger #1 (condition proven on all 33 node-runs of benches 3-5; that it produced the bytes ≈ 60 %)**: every bench node ran
  its whole load in a part of `mdbx.dat` that had no `MADV_RANDOM`. `devnet-finalize.sh --stage-only` starts each node once (creates
  the DB, grows the file to 4 GiB, writes genesis); `--start-all` is then the SECOND open, and on a re-open libmdbx advises only
  `[0, used)` = the genesis pages (mdbx.c:20618). The edge moves only when the file grows (mdbx.c:19935-19943) and it never grew
  (`db_bytes` 4.00 GiB from first to last sample on every node). Smoke-confirmed: the creating process advises the whole 4.295 GB,
  a re-opened DB only its 0.201 GB used size.
- Two routes can build the large folios inside that region, not separated by code reading: R1 mmap read-around at the growth
  frontier; R2 libmdbx's multi-page prefault `pwritev` (up to 64 pages → write-sized folios up to 256 KB, mdbx.c:22367-22389).
  **`MADV_RANDOM` closes R1 but not R2.** With whole-map advice in place, prefault off would close R2 too (probe arm tests it).
- **"Evict `mdbx.dat` before start" does almost nothing**: at start the DB is only genesis and libmdbx already deallocates
  everything past `used` on open (mdbx.c:20582-20615).
- Memory pressure as the escape (≈ 75 %): bench 4 re-read pages from 09:11-09:12 and escaped; bench 5's first re-reads came at
  18:00:54-18:16:49, the window of its late ≈ 20 % drop; bench 3 never re-read and never escaped. Whether reclaim breaks folios up
  is untested (probe arm 8).
- Bench-4 commit cost: **38 µs/tx** (load phase 09:11:59-09:33:50); ≈ 45 µs/tx at bench 5's 6-7 k tx per output; the cleaner target
  is ≈ 1.0 ms per device MB. Documents stop using "35".
- No buffered read or copy of `mdbx.dat` found in the harness, image, CLI or sampler (tn-node-deployment finalize scripts not read).
- U3 notes: one `madvise` per `mdbx.dat` mapping right after `new_database` covers all future growth (libmdbx maps the full 8 TiB
  reservation once); re-apply only after a remap; match the mapping by device and inode, not by path.
- Probe: arms 7 (growth inside the unadvised range) and 8 (reclaim pressure on a resident cache) implemented in the local probe
  crate and smoke-tested; local runbook `run-i1.sh` (11 arms, ≈ 40 min, disk-quiet + MemAvailable ≥ 12 GB); GCE list G0-G7
  (≈ 45 min + VM creation; the binary must be built in a bookworm container for Ubuntu 24.04's glibc).

### Decisions
- D16. **Control arm and the double start**: keep `--stage-only`'s node start in run 1's control arm (comparable to bench 5) —
  orchestrator's proposal: yes for A0; the fix arms then show whether whole-map advice alone repairs a re-opened DB.
- D17. **A prefault-off switch for U3** (a 13th switch) if the local or the GCE probe shows route R2 matters. Orchestrator runs the
  local probe first (≈ 40 min quiet window, announced) and decides the build on its result; the arm use is the user's call.
- D18. The P1 arm keeps the eviction step (harmless, already designed) but it is not expected to matter; the plan's acceptance
  line "fincore 0 after eviction" stays as a harness check only.
- D19. Sampler additions (H4): smaps `rr` coverage, resident pages past `used`, and prefault / `last_pgno` deltas from the node's own
  counters (no `mdbx_stat`).
- The one-VM GCE probe itself is covered by the user's U3 answer (announced, not gated).

## From the harness units (H0, H4, H7a, H7b, H9a/b)
- D20. (RESOLVED 2026-11-11, generator 2b51b2c: tail landings count only under `run.tail_scan`.) **Tail scan and KPI comparability** (H7a): as first built, landings booked during the tail scan counted in the generator's
  landed totals and latency fields, so run 2's published KPIs would have included landings that bench 5's could not. Orchestrator
  action (follows the plan's rule that the headline keeps bench 5's profile and only adds measurements): a generator follow-up
  (H9c) makes every pre-existing field keep its tail-off value and reports the tail only in new fields. No decision needed unless
  the user wants the KPIs redefined.
- D21. Tail-scan length: the plan says 180 s; the I-2 measurement spec recommends 120 s for load blasts. Env files carry 180.
- D22. The unlanded export does up to 30 s of `eth_getTransactionByHash` lookups (≤ 20,000, 64 at a time) against the nodes after
  each blast whenever the landings export is on. It is after the load, outside every measured window.
- D23. Boot image: `BENCH_NODE_BOOT_IMAGE` defaults to `ubuntu-2404-noble-amd64-v20261105` (bench 5's by the earlier gcloud read:
  bench 5 = image v20261105, kernel 7.0.0-1017-gcp). The run artifacts themselves hold no record of the source image; deploy
  step 0 will `images describe` it. Confirm the pin (and that a deprecated image is acceptable if Google has since deprecated it).
- D24. arms-summary corrects the commit-cost drift only for blast types that both control arms ran (M16 in the planned schedule);
  L and M4 rows carry raw values. Add an L and an M4 to A0′ (+ ≈ 23 min), or accept?
- D25. Persist CSV: one column added after the freeze, `mdbx_dat_resident_past_used_pages` (H4 follow-up), read from the node's
  `tn_reth_mdbx_used_bytes` gauge; the folio census needs root on the node for folio orders (the sampler service runs as root).
- D26. **Archive before or after the fleet is deleted** (H6a): the teardown now uploads and verifies the run's results BEFORE it
  deletes anything, so the eleven VMs stay up for the upload (bench 5's 2.5 GB ≈ 5-14 min at this uplink; a run with debug logs is
  far larger). `BENCH_TEARDOWN_SKIP_ARCHIVE=1` skips that gate; the local gate still protects the results. Orchestrator's proposal for
  both bench-6 runs: skip the gate in the teardown and run `tools/archive-run.sh --run <R>` right after it (verify included).
- D27. `unsent` after a late blaster create (H1a): true only when every delete returned before the common start time; GCE deletes
  often take 20-60 s against a 30-s margin, so a slow create on a light blast (150-s lead) may cost a re-fund. A stronger fix (a
  cancel object the blaster checks before it starts) is not built.

## From the local probe (I-1r; run 2026-11-11T15:43:55Z-16:08:31Z on an idle machine; `mdbx-writeback-probe/results/i1-20261111T154355Z/`)
Read off the run log by the orchestrator; the analysis unit I-1r verifies and extends (`benchmark/private/bench6-prep/I-1r/`).

| arm | device ÷ MDBX-dirtied (median) |
|---|---:|
| 7-default: re-opened DB, growth in the unadvised range, node defaults (prefault on) | 1.000 |
| 7-ovf: + two-page overflow values | 1.008 |
| 7-pfoff: prefault off (positive control) | 8.686 |
| 7-pfoff-mrand: prefault off + whole-map `MADV_RANDOM` | 1.000 |
| 7-ovf-mrand / 7-ovf-pfoff-mrand | 1.008 / 1.000 |
| 7-noreopen-pfoff (negative control) | 1.000 |
| 8-readused-nopressure: used range read through the page cache | 5.37 (wide band) |
| 8-readused: the same, 40 MiB of reclaim before every output from output 20 | 5.10 before, 1.34 from output 20 |
| 8-cold-normal: cold cache, `MADV_NORMAL`, same pressure | 1.14 before, 1.15 after |

### What it establishes
- Whole-map `MADV_RANDOM` (the U3 fix) closes the read-around route completely where it occurs (8.69 → 1.000).
- **I-1's falsifier fired**: under the node's defaults (prefault on) the re-open condition alone stays at 1.000 on this kernel. The
  ranked trigger #1 is therefore NOT sufficient as stated. What gives a real node its large folios is open again.
- The multi-page prefault route (R2) was barely exercised (two-page allocations only).
- Reclaim pressure does break up a resident large-folio cache (5.1 → 1.34 within the run): supports "memory pressure took bench 4
  out" and bench 5's late drop.
- Caveats: swap was 8 GB in use at the start; arm 8 has a wide band; one summary line carries an arithmetic overflow in `grown`.

### Decisions
- D28. **The first persist arm of run 1 may not show the planned recovery.** Until the GCE probe or run 1's control arm identifies
  what builds the folios on a node, "commit 178 → 25-38 µs/tx" is a hope, not an expectation. Candidates I-1r is checking:
  prefault effectively off on the node (another process enabling libmdbx's read-ahead edge through the shared lock file; then the
  8.7× arm IS the node's case and U3 fixes it); multi-page GC/freelist records (bench 5's freelist reached 58-59 k entries, rewritten
  every commit in `pwritev` runs of up to 64 pages — would also fit the +0.031 s/min commit drift); output and database size; the
  GCE kernel and filesystem.
- D17 (prefault-off switch) stays undecided: with whole-map advice, prefault off measured 1.000 locally (safe), but no evidence yet
  that the prefault route matters. Decide after I-1r and the GCE probe.
- The GCE probe's arm list is being revised by I-1r (`I-1r/gce-arms.md`) with realistic multi-page arms; the probe driver takes its
  arms from a table.

## From U1 (proposer fix, both variants built; `tasks/checkpoint-bench6-u1.md`)
- Self-feeding model, ten in-step nodes over 20 rounds: under "always" (K = 0) the lag reaches exactly 8 outputs by round 9 and
  stays there with `exec_basis=floor`; under the adaptive policy (K = 4) the lag is 0 on every header; three nodes cancelled after
  round 5 trail by one output for four rounds and return to 0; the whole fleet cancelled at once climbs 1, 2, 3, 4 and returns to 0.
- With the switch off the proposed header's bytes and digest equal today's.
- D29. **When K resets** (deviation from the brief, kept; the domain reviewer agrees): K returns to its configured value only when
  an own header proposed OUTSIDE a starved window certifies. Under the literal reading ("any certified own header") K would reset
  every window, since headers inside a window certify by construction, and a node that stays ahead would lose about 2 headers in
  every K + 2 rounds. Confirm this reading.
- D30. **Leader rounds** (not built; reviewer's suggestion): a failed return to the tip can land on the node's own leader round and
  cost that leader slot; staying in the window when this node is the round's leader would avoid it. Build it, or measure first?
  Orchestrator: measure in run 1 (leader rounds lost per validator in the V arm), build only if it shows.
- For the analysis: under the rule a leader's named block is older than its tip, so the subscriber's wait floor
  (`subscriber.rs:1385`) is up to 8 outputs lower and up to 8 more outputs can be assembled ahead of execution;
  `base_execution_block` (`state.rs:786`) is the named block, not the leader's tip.
