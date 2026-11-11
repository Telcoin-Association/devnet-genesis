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
| 8-readused: the same in the unadvised state, 40 MiB of reclaim before every output from output 20 | 11.44 before, 4.33 from output 20 (held 10.8-11.1 for 15 reclaims, then settled at 4.25-4.3) |
| 8-readused-random: the same under libmdbx's own `MADV_RANDOM` | 5.10 before, 1.34 from output 20, 1.00 by outputs 50-59 |
| 8-cold-normal: cold cache, `MADV_NORMAL`, same pressure | 1.14 before, 1.15 after |

### What it establishes
- Whole-map `MADV_RANDOM` (the U3 fix) closes the read-around route completely where it occurs (8.69 → 1.000).
- **I-1's falsifier fired**: under the node's defaults (prefault on) the re-open condition alone stays at 1.000 on this kernel. The
  ranked trigger #1 is therefore NOT sufficient as stated. What gives a real node its large folios is open again.
- The multi-page prefault route (R2) was barely exercised (two-page allocations only).
- Reclaim pressure breaks up a resident large-folio cache fully only where the range is advised (5.1 → 1.00); in the unadvised
  state it falls 11.4 → 4.3 and stays there. Consistent with "pressure took bench 4 out" and with bench 5's late partial drop.
  (Correction: the orchestrator's first reading had these two rows swapped.) Identical arm-8 set-ups gave 5.25 and 11.66 before
  pressure, so compare within a row only.
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

## From I-1r (analysis of the local probe; `benchmark/private/bench6-prep/I-1r/{verdict.md,gce-arms.md,probe-changes.md}`)
### What still separates a node from the probe's node-default arm (ranked; confidence that it explains bench 5)
1. **The GCE kernel or ext4/hyperdisk builds large folios even with prefault on — 35 %.** Bench 5's 222-228 KB write ops from
   minute 1 cannot be produced on xerxes. The GCE arm `g5-7default` decides it.
2. **A foreign opener switches prefault off — 10 % for bench 5, certain for bench 6 if anyone does it.** Any open of the live
   environment without `MDBX_NORDAHEAD` sets a read-ahead bit in the shared lock file, and the prefault check is evaluated with
   pgno == 0 (`mdbx.c:22445`, `:22494-22500`), so prefault goes off for EVERY allocation (not "below the edge" as the design report
   said) until the next 4 GiB growth. No such opener was found in bench 5 (the node and `telcoin db` use NORDAHEAD; the image ships
   only `telcoin`; the harness, finalize and tn-node-deployment open nothing). A stock `mdbx_stat` would turn a node into the 8.7× arm
   (smoke-confirmed: prefault per grown page 1.000 → 0.000, 37 pages past used).
3. A multi-page prefault that leaves its tail unwritten, seeding read-around — 10 %.
4. Multi-page allocations at real sizes — 5 %: GC records are ONE page each under BIGFOOT (1,018 page numbers max), so bench 5's
   58 k freelist is about 58 one-page records, not one large record (the orchestrator's freelist idea is thereby mostly ruled out).
5. Refault read-around under pressure: a contributor once reclaim runs, not the trigger. 6. Output and database size: < 5 %.
The figures sum to well under 100 %: the cause on a node is NOT identified. The VM run and run 1's control arm decide.

### Actions taken
- Probe crate extended (peer open with and without NORDAHEAD, a long reader, an in-binary `pwritev` counter, GC/freelist columns);
  smoke only. GCE arm list revised to nineteen arms, ≈ 55 min (`I-1r/gce-arms.md`); the probe driver unit is folding it in.
- U3's brief: `persisted output` also carries `prefault_wchar_bytes`, `freelist_pages`, `gc_entries`, `gc_large_pages` (and, if
  cheap, the read-ahead bit), so that run 1's control arm can tell prefault-on from prefault-off on a real node:
  Δ`page_prefault` ≈ 0 while the database grows means prefault is off.
- Rule added for every unit and every run: **no MDBX tool or reader other than the node itself ever opens a live node's database.**

### Decisions
- D31. Approve the ≈ 55-minute one-VM run with the revised arms (covered by the earlier answer on the GCE probe; restated because
  the list grew from 14 to 19 arms and ≈ 45 to ≈ 55 minutes). The never-cut set is eight arms if it must be shorter.
- D32. The planned "no node start in the stage-only step" change has no local evidence behind it unless `g5-7default` amplifies on GCE:
  hold it until the VM run.
- D33. Report the pgno == 0 prefault quirk to libmdbx upstream (after G4)?
- D28 stands: the first persist arm of run 1 may not show the planned recovery.

## From U2 (voter fix; `tasks/checkpoint-bench6-u2.md`) and H1b (blast driver)
- U2 as built: the per-author mark is checked before the wait, after it, and a third time right after the lock is taken (the
  domain review's one finding: a request that went stale while queued on the lock was still served in full). Under the lock the
  execution check has no wait; a database miss is "behind", never a fork. `SupersededRequest` is recoverable and carries no penalty;
  the requester retries it (250 ms, six times, then back-off until a newer own header cancels it).
- D34. **Request time against the libp2p timeout**: with `vote_queue_fix` on, the pre-lock wait (up to 1 s) runs outside
  `vote_timeout`, and the config check only keeps `vote_timeout` under the 10-s libp2p request timeout. Upstream the check should
  require `vote_timeout + 1 s < 10 s` when the switch is on (latency only, not safety). Not built for the bench image; goes into the
  upstream PR (W8) unless the user wants it now.
- D35. **Spam cost** (I-4 item 6): the pre-lock wait runs before header validation and the parent-count bound, so a committee
  member's requests can each be held up to 1 s; only an enforcing per-peer serve budget caps that and the default is unbounded.
  The reviewer judged it small. Upstream question for #1804's PR.
- Deviation kept (reviewer agrees): the mark refuses only a same-epoch lower round, so a header from an earlier epoch keeps today's
  fatal `InvalidEpoch` instead of an endless recoverable retry.
- H1b: `pool_at_start` is read from Prometheus one second before each blast's start (the node's RPC does not expose txpool),
  recorded per blast, with a warning above 1,000 queued; record-only as proposed in D12 (no blocking). A 150-s light-blast lead is
  safe because the late-start guard cuts every create at start − 30 s: a slow create costs one unsent attempt, never a late blaster.

## From U4a (recovery pool) and U0c (plumbing)
- The dedicated pool is process-wide, built lazily on the first non-empty output, so a failed build warns mid-run (then recovery
  uses the global pool; never a panic). `recovery_threads` has no upper cap. Dropping a recovery handle at an epoch close does not
  cancel its job: up to 8 leftover recoveries can occupy a 3-thread pool and the next epoch's first job waits behind them (the
  global pool behaved the same, a small pool makes it more visible) — watch `recover_ms` after boundaries in the POOL+LOCAL arm.
- Rayon's global pool is also used on the execute path by `finish` (two sites) and by persist (sorts); the state root is
  single-threaded. D4 (a separate pool for root/finish) therefore reduces to "finish only"; the contention bench (U4b) measures it.
- D36. Criterion is not a dependency of the workspace; the orchestrator did not add it. The contention bench is a plain timed
  binary like the repo's existing bench. Confirm, or ask for Criterion (a new dependency tree in `Cargo.lock`).
- The switch line renders a zero duration as `0s` and a duration such as 1.5 s as `1s 500ms` (a space): harness readers compare
  durations by value, and the arm values in use (150 ms, 100 ms) are unaffected.

## From U9 (parent grace; `tasks/checkpoint-bench6-u9.md`)
- As built: when the proposer is ready and the max-delay path did not fire, it waits up to G for the authors its LAST own header
  carried as parents and that are missing now; it proposes as soon as they are all in or G expires; a max-delay tick or a jump to
  newer parents ends the grace. At most one grace per round; never below quorum; G is capped at `max_header_delay`; no grace in the
  first two rounds of an epoch, after a skipped round, or after a restart until a header is built. With G = 0 no timer exists.
- The two voter cases for the proposer fix hold with `vote_queue_fix` off and on: an old executed block is voted for at once, also
  when it has left the ring (confirmed from the canonical database); an old number with another hash is refused as
  `UnknownExecutionResult`, never as "behind".
- D37. **Whose certificate was late** is not recorded: `tn_primary_late_parents_total{origin}` has static labels only. The #1803 field
  "own certificates of the two far validators committed ≥ 90 %" comes from the certification analysis (per-validator committed
  share), which exists; a per-late-certificate log line would add the author. Orchestrator: not needed for run 1.
- D38. **Cost bound for upstream** (reviewer): a slow or Byzantine author can delay its certificate past G; one author can do it
  every other round, two alternating authors every round. The cost per round is at most G and never exceeds `max_header_delay`.
  Goes into the PR text so G stays small.
- `missing` can include the proposer's own authority: a node whose own header fails to certify sees `expired` outcomes (read the
  grace counters together with the certification share).
- Two existing run-loop quirks seen while testing, unchanged (candidates for upstream notes): both interval timers fire once at
  start, so round 2 goes out the moment its parents arrive; `handle_proposal_result` resets `advance_round`, so parents that arrive
  while a header is still pending lose their readiness until the max delay.

## From U6a (sealed-transaction store; `tasks/bench6/briefs/u6a-api.md`)
- Deviation from the design, kept: marking needs a **seal ticket** taken when the batch is built. The worker acks a batch only after
  reporting its digest, so under load the batch can execute before the builder handles the ack; a mark made then would leave a
  skipped transaction marked for good. `mark_sealed` refuses when the digest has executed since the ticket.
- A canonical-state broadcast lag drops every mark (the digests executed in the lost rounds are unknown): at most one duplicate
  copy per affected transaction, which execution skips, instead of a sender blocked for good.
- Sealed transactions now hold pool capacity until execution, including reth's 256 per-sender slots (bench windows are 16 and 4).
  This interacts with D12 (pool hygiene): the queued and pending gauges will read higher with the switch on; compare arms with that
  in mind.
- A node that leaves the committee kept marks under orphaned digests; the batch-builder unit (U6b) clears them at the epoch close.
- Left to the e2e test: the epoch-boundary loss path (I-2's S6) and a restart with marks (S9).

## From H11 (launchers and the arm sequencer; `benchmark/launch/README.md`)
- Default run-1 walk as built (14 blasts): A0 control I, L, M4, M16 → P1 M16 → V L, M16 → POOL+LOCAL M16 with an epoch boundary
  ≈ 240 s into its mixed phase → PIPE M4, M16 → BOUND M4, M16 → GR150 I, L, short M16 → A0′ M16. The table is
  `benchmark/launch/bench6-run1.plan`, edited by hand at G2.
- The sequencer stops by itself on: a node failing its restart or readback, two guard deferrals, a blast failing twice or
  aborting on fleet health, queued pools ≥ 1,000 before a saturated blast (it waits up to 10 min first), a commit stall > 120 s
  after a blast, a root disk > 85 %, a fatal database line in the newest status. It always prints the resume command.
- D39. **What the sequencer does not watch** (the orchestrator's watch items during run 1): a fatal database failure inside a long
  step (only the newest status line is read), a commit stall while idle, the BOUND entry rule (abort the arm when a validator
  enters ≥ 30 rounds behind: read `tn_primary_epoch_entry_rounds_behind`), memory late in the run, and "read the vote arm before
  PIPE or BOUND" (the plan's rule): the sequencer walks straight through unless told `--only-arm`. Orchestrator's proposal: run 1
  as three launches — arms 0-2 (control, P1, V), a read of the vote arm, then arms 3-7 — so the rule is kept without a stop
  inside the tool.
- D40. A resume re-applies the arm under a new name, and an arm with `host evict-mdbx` then restarts every node again (≈ 10 min).
- D41. Unreadable pools at the deadline let the walk go on with a note (the blast's own preflight fails if the obs VM is down);
  make the gate strict?
- Run-1 blasts are hand `fund` / `run` calls, recorded in `blast_runs[]` and each blast's archived directory, not in `blasts[]`.
  A rehearsal unit (H12) is checking that every reader copes before the fleet is paid for.
- A filled env file inside `benchmark/` must be committed before a launch (the launcher refuses a dirty harness tree).

## From U5 (tracker drain and the final-state check; `tasks/checkpoint-bench6-u5.md`)
- As built: with `epoch_close_task_drain` on, the boundary handler drives close, record and export through `track_while`, which
  keeps draining the tracking channel and reaping tasks and can never drop the future (tested with a critical task ending,
  failing and panicking while the future sits between the record save and the persist). With `epoch_record_state_check` on, a
  STORED epoch record whose final state is not this node's closing block halts the node with an error naming both blocks.
- Correction to an earlier note: an empty recent-blocks ring answers the default header (block 0 with a fixed non-zero hash), not
  (0, zero hash); a record is never written in that state today (the committee read fails and the node halts). So "skip the check
  when the ring is empty" is safe as built: it warns and counts.
- D42. **The halt does not survive a restart** (reviewer, Low): after the halt the closing block is executed; on restart the node
  enters the next epoch and never compares the stored record again. No worse than bench 5. A fix (compare record N−1's final
  state with the canonical header at start, behind the switch) needs its own skip rules for nodes restored from a snapshot. Not
  built. Upstream question for #1806's PR; for the bench the check is on only as a tripwire.
- D43. `wait_for_exit`'s 200-ms grace does not read the channel: > 1,000 spawns inside it would overflow again (bench 5's rate gives
  about 18). Not fixed.
- D44. The switch's doc in `crates/config/src/node.rs` describes a check on the freshly built record; the code checks a STORED
  record. One-sentence doc fix at integration (orchestrator). DONE 2026-11-11 (2c9b43209 on the integration branch).
- Not delivered on purpose: an entry-lag-in-seconds gauge (#1806 E); the rounds-behind gauge in the primary crate covers the arm rule.

## From U12a (pipelined persist, core; `tasks/bench6/briefs/u12a-api.md`) — held off the integration branch until last
- Three commits, 544 tests, the domain review (execution, storage, epoch) approved with nothing at medium or above. With the
  switch off no new code runs on the engine's path. The build/commit split of `payload_builder.rs` is a refactor of the
  SEQUENTIAL path too (the existing 27-test engine suite passes unchanged): it lands only if pipelined persist makes the image.
- The riskiest invariant is pinned: every state root of N+1 reads one snapshot taken before N's persist starts. A hand mutation
  that opens a fresh transaction per root is caught by `test_pinned_anchor_root_ignores_later_commit`.
- D45. The pinned read transaction falls under libmdbx's 5-minute read-transaction timeout: a build or persist longer than that
  would stop the node. Unreachable at bench timings (persist ≈ 1.2 s); a statement for the PR.
- D46. Go/no-go status (D7): gates 1 and 2 (differential proptest, persist faults) are being written by an independent test unit
  now; gate 3 (epoch-close barrier) and gate 4 (e2e sets, 2-on/2-off fleet) need the wiring unit, which waits for U3.

## From U3 (MDBX advice and the storage fields; `tasks/checkpoint-bench6-u3.md`)
- As built: with `mdbx_random_advice` on, right after the database is opened the node finds every mapping of its own `mdbx.dat`
  (identified through the address of a record it reads, so it is exact on any file system) and applies `MADV_RANDOM`; one call
  covers all future growth because libmdbx maps its whole reservation once; it re-checks after each persist with one map-size
  comparison. No vendored edit. A failed advice warns once and never fails the open.
- The control arm can now tell which case a node is in from its own log: prefault on ⇔ Δ`page_prefault` ≈ Δ`mdbx_last_pgno` per
  persist; the amplification is device bytes ÷ ((`page_newly` + `page_cow`) × 4096). Reading the counters costs ≈ 115 µs per persist.
- `freelist_pages` per persist is NOT logged (it needs a walk of the whole GC table, which with the switch off could itself
  fault pages through read-around); reth's existing `db.freelist` gauge has it at scrape granularity.
- D17 (prefault-off switch) is cheap to add if the GCE probe calls for it: one `mdbx_env_set_option` call beside the advice, a
  switch that requires `mdbx_random_advice` (prefault off WITHOUT whole-map advice is the 8.7× case), plus the config field, the
  plumbing and the harness row. Not built; decide after the VM run.

## From U11 (RPC admission bound; `tasks/checkpoint-bench6-u11.md`)
- As built: with `rpc_admission_backlog_outputs: K` an ACTIVE validator refuses `eth_sendRawTransaction` (and the sync variant)
  with −32003 "txpool is full" once the engine is K outputs behind what the node has forwarded to it, and admits again only when
  the backlog is back at 0. The check runs before any decoding. Off (0) costs one `None` check per request.
- D47. **What the arm will look like under saturation.** The gate stays closed for as long as the engine needs to execute and
  persist everything admitted while it was open, so under a saturating load it is closed most of the time. The generator
  resends a refused transaction for about 30 s and DROPS it on the 22nd refusal (without advancing the nonce). So this arm
  trades queue depth for client-side refusals and, past 30 s, drops: its verdict must be read on landed tx/s AND on the
  refused/dropped counts and the confirmation latency of what was admitted, not on throughput alone. Whether the arm is run at
  the saturating rate or at a rate just above the execution ceiling is a question for the gate.
- D48. Validators' backlogs rise together, so their gates close together; there is no jitter. An observer's forwarder then walks
  the whole committee, logs a warn per transaction per pass and requeues. Not changed (it needs `forward.rs`).
- D49. A limit above about 73 can never close (64 in the channel + 8 queued + 1 executing); K = 1 closes whenever any output is
  in flight. One sentence for the config docs (orchestrator, with D44). DONE 2026-11-11 (74662a889).
- D50. Only active validators are gated; observers' own submissions pass (their pool feeds the validators' gates). One-line
  change if the user wants observers gated too.
- The gauge `tn_node_execution_backlog_outputs` is set only when an output is forwarded: during a consensus stall it freezes
  while the gate (which reads the live value) may already have reopened. Read the gate from the refusal counter, not the gauge.
- D9 stands (2 or 3 with pipelining): with pipelined persist "executed" must still mean durable — the wiring unit decides and
  documents it.

## From U6b (sealed-keep, the batch builder; `tasks/checkpoint-bench6-u6b.md`)
- As built: with `sealed_tx_keep` on, a quorum-sealing worker's builder takes a ticket before it seals, marks the batch's
  transactions on the quorum ack and leaves them in the pool; selection skips a marked transaction (and counts it); a failed,
  refused or unreported seal never marks. An epoch close clears the marks of every orphaned digest on every pool before the
  orphan recovery runs. A failure of the mark itself falls back to today's prune for that one batch and logs an error.
- **The switch needed a node wiring commit the unit could not make** (the builder cannot see whether its worker seals through a
  quorum). It is on the integration branch (3ee6b629f) with a unit test; the live proof is `batch builder started …
  keeps_sealed=true` on every validator and `tn_reth_sealed_txs_marked > 0` under load. The run-1 checklist gets this line.
- I-2's cases at builder level, each with a switch-off pin that reproduces bench 5: S1 (a batch executed out of order is
  re-sealed and lands exactly once, no client resend), S2 (a resend of a sealed batch is `already known`), S3 (a resend of a
  subset is `already known`; off: it seals a NEW digest — the double execution).
- D51. Residuals, not fixed: a marked transaction can still be replaced by a fee bump (the replacement is unmarked); a batch
  whose header never certifies holds its marks until the epoch's orphan pass and a resend cannot free them; on the
  non-validator orphan branch a disbursed orphan's transactions are forwarded a second time (execution skips the copy); marks
  are in memory, so after a restart the orphan pass is the only recovery (S9, e2e).
- With the switch on, "pending" on the builder's lines and gauge includes in-flight sealed transactions, and every kept batch
  is followed by one build that walks only sealed transactions: the analysis must not read either as a regression.
- Still to show end to end (the next e2e unit): S1 on a running fleet, S6 (failed report at the boundary), S9 (restart), a real
  queued-limit eviction (S7), and the effective mode on a live validator.

## From U12b (pipelined persist, wiring; `tasks/checkpoint-bench6-u12b.md`) — still held off the integration branch
- As built: `run()` reads the switch once. Off: `run_sequential`, the old loop moved verbatim (same sha256 of the body; the only
  line removed from `lib.rs` is the old signature; the 27-test engine suite passes unchanged). On: `run_pipelined` drives the
  two-slot pipeline, returns only when the queue is empty AND the pipeline is idle, lets every output in flight commit before it
  returns an error, and fails closed if it ever has nothing to wait on.
- Go/no-go (D7) so far: gate 3 (the epoch-close barrier test) PASS — it fails when the barrier is removed by hand; the engine's
  existing differential test passes with the switch forced on. Gates 1 and 2 (differential proptest, persist faults): the
  independent test unit is still running. Gate 4 (e2e sets and the 2-on/2-off fleet): next. Gate 5 (cycle ≤ 1.1 × max(execute,
  persist)) has no measurement yet. Gate 6: the domain review approved with two Low findings, both fixed.
- **D9 is settled by the mechanics, not by taste: 3 with pipelining on.** A pipelined node that keeps up reads 2 outputs behind
  (one committing, one building), so a bound of 2 would hold the gate closed whenever there is load. The arm files `bound`,
  `gr150`, `gr100` carry `pipelined_persist true` with a bound of 2 today: they change to 3 if pipelined persist makes the
  image, and stay at 2 with `pipelined_persist` removed if it does not. The epoch-close backlog gauge reads one higher too.
- D52. What "executed" means under pipelining: durable AND announced (recorded at the commit), as in the sequential loop. An
  output that is built but not durable counts as behind for the admission bound and the epoch-close gauge.
- D53 (was D8). With the switch on, RPC `latest` can show blocks of up to two outputs that are not durable yet (sequential:
  one). A crash loses them and replay rebuilds the same blocks. For the PR text.
- D54. The barrier's stated reason in the design was too strong: what keeps the next epoch's first output off the closing block
  is the forwarder sending nothing past a close (as today); the engine-side barrier is a second line. The docs now say so.
- D55. The pipelined series (`tn_engine_unpersisted_outputs`, `…built_height`, `…persist_wait_seconds`,
  `…commit_interval_seconds`, `…close_barrier_holds_total`) export 0 on a sequential node; the sequential arm's cycle is
  `execution_duration_seconds`. In pipelined mode `execution_duration_seconds` and the `output execution task finished` line's
  `task_ms` run from build start to COMMIT: the per-output time is not comparable across the two modes without the lap fields.
- D56. `proc_write_bytes` on `persisted output` is process-wide: with a build overlapping the persist it also holds that
  build's log writes. Treat it as an upper bound in pipelined arms; the page-operation deltas are unaffected (single writer).
- D45 stands (5-minute read-transaction timeout). A stale output halts a pipelined node where the sequential one would run it
  twice (info).
- The test delay hook (`TN_TEST_EXECUTION_DELAY_MS`) only slowed the sequential task; the orchestrator added it to the
  pipelined build task so the slow-executor e2e tests mean the same thing with the switch on.

## From H12 (rehearsal of run 1's data path; `tasks/checkpoint-bench6-H12.md`)
- The real `run-arms.sh`, arm tool and blast driver were walked in a sandbox through: a failed blast retried, a blast failing
  twice (the sequencer stops with the arm open), a resume (`--from-arm`), and the return to defaults. Every start line of
  every node matched its arm (44 of 44), the resumed arm included.
- **One bug that would have mismeasured run 1, fixed:** the summary tool counted FAILED hand-run blasts as measured rows (it
  never read their return code) and gave a resumed arm the wrong role. It now builds an entry for a hand-run blast from the
  blast's own records, picks the arm by its begin, and lists failed blasts as "not measured". Bench 5's self-check is
  unchanged (EXIT 0).
- Driver gaps, ranked (none loses a measurement; all are closed by the next harness unit before run 1 unless noted):
  1. The sequencer's own log (retries, pool-gate readings, the planned epoch boundary) is written outside `results/`, so the
     archive and the bundle never see it.
  2. No hand-run blast writes `blasts[]`, so the report's window helpers (light, load, floor blast) find nothing in a run made
     of hand runs. Fix at the root: the blast driver records the same entry for a hand run as for a scripted one.
  3. `blast_runs[]` lacks kind, senders, window and phase seconds (closed by 2).
  4. `blast_runs[].log` points at the path a log had before it was archived.
  5. Reader side: `stage-latency.py` without `--windows` keeps failed blasts; the phase windows of three tools come from the
     live manifest only (the last blast); `cert-rate.py` has no window for an idle mark.
- D57. The rehearsal module takes about 4 minutes: keep it in the gate (recommended: it is the only test of the whole data
  path) or run it on request.

## From ST-U12a (differential and persist-fault tests of the pipelined core; `tasks/checkpoint-bench6-st-u12a.md`)
- **Go/no-go gates 1 and 2: PASS, no finding against the core.** An independent agent that had not written the core drove the
  pipeline against the sequential path as an oracle: 64 generated cases by default and a 400-case hunt (2,776 blocks, 711
  seeded builds, 253 commits landing in the middle of the next build), with the previous commit released before, during or
  after each build. Every block, receipt, trie digest and engine update matched. The fault property (a persist failing early
  or late, then restart and replay) held in 400 of 400 cases: the database ends at the last durable output, memory is rolled
  back, the pipeline refuses to continue, and the replay reaches the oracle's chain.
- The tests bite: three hand mutations of the core (a seeded build that skips the committing output's deltas; an announce
  before the persist; a rollback that keeps a block) fail 7, 8 and 3 of the 8 new tests.
- Limits, stated: the database comparison covers blocks, receipts and the trie and hashed tables, not plain state, change sets
  or history (a divergence there would show in later roots within a case); a commit landing between two blocks of the next
  build is reached by timing here — the wiring unit's own test forces it deterministically.
- Gate 5 (the cycle bench) was not written by this unit: a separate small unit writes it; the orchestrator runs it on a quiet
  host.

## From H13 (driver gaps closed; `tasks/checkpoint-bench6-H13.md`)
- A blast started by hand now leaves the same `blasts[]` entry as a scripted one (failed ones included, with their rc), the
  blast's type is in its own record, no log path dangles, and the sequencer's log is written under `results/<run>/logs/` as
  it runs. A deploy-driven blast (run 2's path) writes exactly what it wrote before.
- D58. **Found, not yet fixed: a TERM to the arms segment kills the sequencer but not the blast it started.** The segment
  reports `rc=143` at once while a blast is still loading the fleet, and the orphaned driver finishes and deletes its VMs on
  its own. Nothing is lost, but "ended" is not true. The next harness unit makes a stop signal finish the running blast,
  start nothing new, and write the rc line only when nothing of the segment is left running. Until then: after stopping a
  walk, wait for `benchmark-blast.sh` to exit before any other fleet action.
- Readers still to fix (next unit): `stage-latency.py` without `--windows` names failed blasts as measured ones; the floor-blast
  helper takes the first entry of an index even when a retry under the same index succeeded; three tools take phase windows
  from the live manifest only (the last blast).

## From the topic reviews (code review + security evaluation, findings verified; reports under `tasks/bench6/review/`)
### digest-dedupe (#1807) — APPROVE WITH FOLLOW-UPS; nothing Critical, High or Medium; nothing to change before the image
- Switch off: every path is the previous behaviour (two counters registered at 0; one debug field that copies an address
  already recovered). Mixed fleet: safe — the switch only changes which of a node's OWN digests go into its own headers, and
  voters do not check duplicates, minimum size or order.
- The central question (can either half drop the only live copy of a digest?): no path found; in the worst case a batch waits
  for the node's next own commit or the next epoch start, and its cache row survives.
- D59 (Low, plausible; before the upstream PR): a commit-notice window. The own-headers commit notice goes out after the loop
  that sequences sub-dags, so a batch's cache row can be evicted before the proposer learns its header committed; an identical
  re-seal in that window is dropped by the proposer and then suppressed by the worker for the rest of the run. Only
  transactions the first copy skipped are affected, and they wait for orphan recovery (delayed, not lost). The window widens
  when execution lags — which is what a benchmark does. Either document it or send each sub-dag's own committed rounds
  inside the loop.
- D60 (before the upstream PR): no test runs the real worker against the real proposer; two proposer tests are sketched in
  the report.
- Doc fix made (b89ad570f): the config doc now says the worker needs the primary's ack of its latest seal AND the cache row.
- For reading the benchmark (the reviewer's inference): with `sealed_tx_keep` on the worker-side counter should stay near 0;
  judge the proposer counter and the duplicate-digests-executed check.

## From ST-A (first e2e of the vote fix, the drain and a mixed-switch fleet; `tasks/checkpoint-bench6-st-a.md`)
Four local validators, three of them executing 1.75 s late per output, production header cadence, 90-s windows, three runs.
- **D1 has evidence now.** Fast node's own headers certified: switches off 0.53 / 0.69 / 0.71 (each slow voter refused 25-42
  headers as "execution behind"); **adaptive (K = 4) 0.81 / 0.81 / 0.82**; **always (K = 0) 1.00 / 0.99 / 0.99** with 0
  refusals and the named block on the floor for most headers. The slow nodes certify 1.00 in every arm; all four hold the
  same blocks in every arm.
- D61. **The adaptive form as built misses the 98 % target** (finding against D29's reset rule, not a fork): in a regime where
  a tip header certifies part of the time, one certified tip header resets the window to 4, so the node returns to its tip
  every 4-16 rounds instead of every 128. Headers built under the quorum rule certified every time. A unit is changing the
  reset rule (a RUN of certified tip headers, not one) and re-measuring; until then "always" is the form that meets the
  target locally, at the known cost (D1: the named block ≈ 8 outputs stale).
- The control reproduces bench 5's refusals but not its near-zero share: with outputs committing every second round about
  half the fast node's headers name a block the slow voters reach in time. A deeper lag cannot be forced with this hook
  without also defeating the fix (past 8 ring entries the floor block is unexecuted too) — a limit of the test, stated.
- **A mixed-switch fleet is one chain: YES** (3 of 3): two validators with nine switches on, two with none, heavy load, epoch
  boundaries and a restart of a switched-on node; certified epoch records for epochs 0-2 on every node with matching final
  blocks; no halt, no canary line.
- **The drain: no regression, but the overflow is NOT SHOWN fixed at this scale.** The control never overflows the tracking
  channel on four local nodes (bench 5 needed a loaded ten-node fleet), so the test pins that the close completes, the drain
  line appears, the final-state check stays quiet and no tracking failure is logged. Run 1's fleet is the first real test.
- One port collision at a node start in a calibration run (the harness's port allocator against a process outside the
  test); it did not recur.

### parent-grace (#1803) — CHANGES REQUIRED; no Critical or High; safe for a mixed fleet (report `tasks/bench6/review/parent-grace-report.md`)
- Switch off: unchanged (metric registrations, one counter on the late-parent arm, `grace_ms=0`, one always-pending select
  branch that changes no decision). Mixed fleet: no fork, no rejection, no stall — only the node's own headers change (later,
  more parents, more digests), and all of it passes the voters' checks.
- **M1 (being fixed before the image): the grace forgets a far validator after ONE miss.** The basis is the authors the last
  own header carried; a certificate that arrives after the header went out is only counted. After one expiry, skipped round,
  restart or epoch start the node is ready before that author's certificate arrives in every later round and never waits
  for it again — the bench-5 drift returns. Fix: a late certificate of the previous round puts its author back in the basis.
- **M2 (being fixed with it) — D62, decided by the orchestrator, reversible:** a round jump during a grace strands the held
  header; if the node leads that round, the leader certificate is missing, every proposer waits out `max_header_delay` (1 s
  on the fleet) and that leader is never committed. Fix chosen: a node that leads the round it is about to propose in does
  not arm a grace (the proposer already gives leaders a zero minimum delay; the far certificates still ride the non-leaders'
  headers). The issue text says the grace "applies to leaders too": that sentence changes with this.
- **M3 — D63, for the gate: the grace is NOT free under load.** With the header ready on the quorum message, every basis
  author outside that message is missing, so the grace arms on almost every round and costs up to G per round. The issue's
  "about 0 under load" and the pass criterion "loaded rounds and throughput unchanged within noise" are wrong. The grace arm
  (GR150) must be judged on certification of the far validators AGAINST the round-time cost, read from
  `tn_primary_parent_grace_wait_seconds`, `tn_primary_parent_grace_total{outcome}` and `grace_ms` on `header proposed`. Whether
  150 ms per round is worth it at ten regions is the question run 1 answers; G = 100 ms is the fallback arm.
- Low (five): a leader-table swap can stretch a hold past G (bounded by the maximum delay); `parent_grace` is capped silently;
  D38 understated what one author can do (an author that lands just inside G costs about G every round, outcome `complete`);
  the log lines cannot name the author waited for; two far validators can wait on each other. The fix unit handles the
  cheap ones and documents the rest.
