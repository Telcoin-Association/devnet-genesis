# Bench 5 analysis brief — run r20261107-1504 (drafted 2026-11-07 16:10Z during the blast; orchestrator fills "Run facts" after the teardown)

Repo /home/drtnarg/coding/telcoin/devnet-genesis (main @ 5c9ba71+; the run's results under benchmark/results/r20261107-1504/ — gitignored).
Rules: tasks/bench5-agent-rules.md HARD RULES apply (no git add/commit/push; no fleet contact — the fleet is DELETED after the teardown, every
input is local; one writer per output dir; budget < 250k tokens; checkpoint tasks/checkpoint-bench5-<unit>.md with a `status:` header rewritten
after each section, read it first and resume from the first unfinished section; hand back a summary, never file dumps). Outputs under
benchmark/private/bench5-r20261107-1504/<unit>/ (gitignored, private: real IPs/ids allowed there, never in tasks/ or the report). Scratch
(bulky copies) under /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/<session>/scratchpad/<unit>/.
Templates = the bench-4 units' outputs and scripts under benchmark/private/bench4-r20261105-0803/{A1,A2,A3,A4n,A4o,P}/ and their checkpoints
tasks/checkpoint-bench4-{A1,A2,A3,A4n,A4o,A5,P}.md; the bench-4 report tasks/bench4-report-r20261105-0803.md; the bench-4 brief
tasks/bench4-analysis-brief.md; the frozen design tasks/checkpoint-bench5-design.md (§F1/§F3/§F2/§LAND carry the exact log-line shapes,
metric names and the **bench-5 verdict fields**; §SEC the restart-gap expectations; "Follow-ups collected during Wave 1" the renamed lines).
The investigation texts tasks/issues/bench5-{f1-commit-lag-demotion,f2-execution-ceiling,f3-rejoin-loop}.md and
tasks/bench5-land-time-baseline.md state what each fix is expected to change — every unit answers "did it?" with the field named there.

## What changed vs bench 4 (r20261105-0803) — read before touching data
- Image adiri @sha256:a1a82341129cfa82bf0f7f19fbfc26f84888995e96333f428bd726462f23e402 = branch bench/main-fixes-2026-11 @ 067639def
  (origin/main 4bf4604d2 + 9 observability commits + 29 topic commits; ledger tasks/bench5-cherrypick-ledger.md maps sha → topic). Topics:
  f1-commit-lag (commit no longer waits for execution; fork check in the subscriber; lag gauges), f3-rejoin (inactive nodes store gossip
  certificates; rejoin at the network head; grace; 2 attempts/epoch; vote refusals while inactive / execution-behind; stalled-head rejoin;
  restored-DAG guard; stuck-replay re-request), log-dumps + exec-split + signer-reuse + cached-reads (engine), land-path-obs (per-batch /
  header / cert / output timing lines), batch-wake, cert-requeue. Same fleet (10 validators + observer-11, ten regions, c3-highcpu-8,
  validator-05 us-east4-b), same parameters (1000/350/250 ms, thr 5, gc 50), same chaos plan, all nodes durable (no --db.sync-mode).
- Generator blast-v2-6dad96f (sha256:5766094d…): scanner records batch_index / batch_digest_prefix / consensus digest and per-block own-submit
  quantiles; `seen_ms` per phase; sampled landings export `landings-*.ndjson.gz` (1 in 100); collector PROM_SERIES extended (E2/E3/L1-L4/F1
  histograms + seal_duration, quorum_wait, proposer_pending_digests + node/txpool/save_blocks series).
- Light-load arm: BENCH_LIGHT_LOAD=1 → four blasts in order, each archived with its own manifest: index 0 `blast-0-<UTC>/` 8 senders ×
  window 16 (warm-up 60 / mixed 360 / cool-down 60, chaos off), index 1 16 senders × 16, index 2 600 senders × window 4 (the reduced-window
  point), index 3 = the bench-4 profile 600 × 16, 120/2400/180 s, chaos on → `blasters/` (the final blast) + `funder/`. KPI floor windows
  come from indices 0-1 (`--blast-dir`), the load KPIs from index 3; index 2 shows latency vs in-flight at saturation (Little's law check).
- Logs: E1 demoted the engine dumps to trace → `engine=debug` is cheap now (expect tens of MB/min per validator under load, LOG_RATE line in
  the blast log); still STREAM (`zcat … | grep -E`), never cat a whole file. New lines (target consensus::metrics unless noted): `batch built`
  (digest, reason, pool_age_p50/max_ms, build_ms, pending_before, wake), `batch sealed … digest quorum_ms`, `batch reported digest report_ms`,
  `header proposed … created_at_ms reason digests oldest_digest_wait_ms pending_before`, `header uncertified round epoch reason`, `certificate
  committed … created_at_ms age_ms`, `subdag committed … leader_created_at_ms commit_timestamp_ms`, `subdag sequenced subdag_index leader_round
  commit_timestamp_ms base_execution_block`, `waited for execution before assembling the output …` (> 1 s only), `consensus output ready …
  fetch_ms leader_epoch`, `output saved number leader_round pack_persist_ms slots_persist_ms`, engine `output queued consensus_number depth`,
  `output execution task finished … forward_wait_ms queue_wait_ms task_ms`, `output executed … txs recover_ms|recover_wait_ms evm_ms root_ms
  finish_ms other_ms max_block_*`, `signers recovered consensus_number txs recover_ms`, `next block executed … consensus_number batch_index
  batch_digest`, `persisted output …`. F1/F3 lines: `we are behind … saved_number backlog_outputs exec_lag_rounds commit_lag_rounds`,
  `primed consensus rounds exec_round newest_round primary_round`, `dag restored num_certs`, `restored dag has a gap above the committed round;
  going inactive … hole_round`, `rejoin not ready reason=`, `attempting to rejoin`, `behind the gc window inside the rejoin grace; holding
  demotion`, `re-requesting consensus outputs behind the gossiped frontier … backoff_ms`, `stalled head not ready`, `vote path timing …
  outcome=` (incl. `behind`), `vote refused`. Metrics: tn_primary_{consensus_exec_lag_rounds,commit_lag_rounds,commit_run_ahead_blocked_total,
  rejoin_grace_holds_total,inactive_certificates_cached_total,votes_refused_inactive_total,votes_refused_execution_behind_total},
  tn_executor_{execution_wait_seconds,rejoin_blocked_total{reason}}, tn_node_mode_transitions_total{to,reason} (reasons incl. outside_gc_window,
  epoch_behind, rejoin, restart_gap, bogus_subdag, stalled_head), tn_engine_{recover,evm,root,finish,forward_wait}_seconds, tn_engine_channel_depth,
  tn_batch_builder_{pool_age_seconds,builds_total{reason}}, tn_worker_batch_report_seconds, tn_primary_{digest_wait_seconds,headers_proposed_total
  {reason}}, consensus_pack_persist_seconds. Prometheus snapshot: results/<run>/logs/bench-obs-prometheus-*.tar.gz (replay with
  prom/prometheus:v3.1.0 on an extracted copy; one copy + port per unit — the TSDB lock forbids sharing).
- Pre-start fsync probe per node: manifest.node_startup[inst].fsync_probe (p50/p95 µs); fleet median 986 µs, slow=[bench-validator-06]
  (1253 µs). RTT matrix for the ten zones incl. us-east4-b: benchmark/latency/2026-11-07/ (UDP headline).

## Run facts (orchestrator; cite, do not re-derive; teardown facts appended below once pulled)
- Deploy `--yes --with-contracts --to 12` 15:04:50-15:50:54Z rc=0: coordinated start 15:23:30Z (A4o from the logs; manifest.coordinated_start), 11/11 started spread 0 s;
  fsync probe median 986 µs, slow=[bench-validator-06] 1253 µs; OBS_STACK_OK 20 s, OBS_READY 47 s; fleet ready 10/10 CvvActive at the first pass; OBSCFG_OK ×11
  restarted=none; POSTCFG_OK ×11 sha 067639def forks subsecond-from-genesis params 1000/350/250 thr 5; ADM_OK ×11 denied 0/0; contracts deployed; bucket
  gs://tn-devnet-bench-r20261107-1504. Idle 15:50:54-16:01:58Z.
- Blast segment `--yes --from 13 --to 15` from 16:01:58Z: step 13 fund ×4 (indices 0-3, BENCH_FUND_DONE rc=0 each); step 14 light sequence:
  index 0 (8 senders × window 16, 60/360/60 s, chaos off) LIGHT_LOAD_START ~16:11Z, blasters start ~16:16Z, all BENCH_BLAST_DONE 16:27:14Z, archive
  `blast-0-20261107T163112Z/`, LIGHT_LOAD_DONE rc=0; index 1 (16 × 16) 16:31Z → 16:47:12Z, `blast-1-20261107T165107Z/`, rc=0; index 2 (600 × window 4)
  16:48Z → 17:08:04Z, `blast-2-20261107T171309Z/`, rc=0. LOG_RATE bench-validator-01: blast 0 8.2, blast 1 8.4, blast 2 (saturation) 10.8 MB/min
  (bench 4: 1,160 MB/min). Index 3 (the configured profile) ABORTED: `gcloud compute instances create bench-blaster-06` crashed client-side
  (ReadTimeout 300 s; the crash log is blast-3-20261107T173343Z/logs/create-bench-blaster-06.log — logs/create-bench-blaster-06.log is index 4's SUCCESSFUL create); of the 9
  created blasters 6 started at 17:17:36Z and 08-10 started 1m40s-1m55s late; each sent at most ~90 s, all inside its warm-up, before the driver's exit cleanup
  stopped them (manifest copy + partial outputs in `blast-3-20261107T173343Z/`, abort reason=interrupted 17:20:07Z); the chaos had NOT fired. Sequence
  rc=1 at 17:29:10Z (BENCH_DEPLOY_RESULT rc=1 last_step=14). A4o: harness defect — one transient gcloud client timeout on a blaster create aborts the blast.
- Resume per the driver's printed instruction: `BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=4 benchmark-blast.sh fund` 17:30:25-17:32:50Z rc=0 (funder-3-20261107T173046Z/
  holds the index-3 funder copy), then `run` 17:32:50Z: 10 blasters × 600 senders @ 400000+, window 16, start_at 17:38:02Z (mixed 17:40:02-18:20:02Z,
  cool-down to 18:23Z); chaos against epoch 7 (opened 17:35:43Z): kill -9 bench-validator-05 17:54:44Z rc=0 (59 s before the 17:55:43Z close; pre-kill
  container log saved on the node as /var/lib/bench-logs/telcoin-pre-kill-20261107T175417Z.log.gz), systemctl start 17:59:44Z rc=0, observer-11 systemctl
  restart 18:04:44Z rc=0; validator-05 polled cvv_inactive from its restart through the end of the load (last driver poll ~18:25Z); BENCH_BLAST_DONE ×10
  rc=0 (blaster-05 first — its node was inactive), all reported 18:25:57Z; validator-05: killed 17:54:44.17Z, process start 17:59:44.51Z, CvvActive briefly then demoted `epoch_behind` 18:00:03.5Z (network already in epoch 8),
  catch-up under saturation (replayed 30.5 outputs/min vs 23.3 produced → +7/min), `attempting to rejoin` round_gap=20 at 18:22:49.65Z → CvvActive 18:22:49.98Z (A3, log + Prometheus),
  i.e. 1-2 min after the load ended at ~18:21:32Z, mid-epoch 9; kill → active 28m05.8s; `blasters/` = index 4 (manifest .blast.run_index 4, chaos 3 entries, abort null);
  run rc=0 18:30:14Z. Epochs 1200 s: epoch 8 17:55:43-18:15:43Z, epoch 9 18:15:43-18:35:43Z.
- Step 15 (`--from 15 --to 15`, BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=4) 18:31:13-18:41:19Z rc=0: collect ok; rejoin wait found validator-05 CvvActive at the
  first poll (consistent with the 18:24:47Z blast-driver poll above: it rejoined MID-EPOCH 9 within ≈ 1-5 min of the load ending; bench 4's chaos node needed the next
  boundary, 36 min); prom_window 15:40:20Z → 18:39:18Z end_reason=fleet_ready (waited 253 s); collector: metrics.json 111 MB, 21 instances, 307 GCP series,
  prometheus missing=0 absent=0 errors=0. Certification deferred to the teardown's log pull.
- A1 DONE (benchmark/private/bench5-r20261107-1504/A1/kpis.md, light.md, kpis.json, kpis_table.md, bundle_*.json; driver reproduces bench 4 and the three earlier runs exactly): index-4 load 3,448.7 tx/s
  (−24.7 % vs 4,578; best 60 s 4,939; 12.96 blocks/s vs 15.84; rounds/s 0.97-1.0 vs 0.84-0.91), land p50/p95 2.81/14.40 s (3.30/12.84), seen p50/p95 14.18/53.39 s (12.92/29.78), bias-free commit p50 3.07 s
  (the whole-second bias is exactly 500 ms mean); FLOOR 8 senders land p50 0.25 s / seen 1.63 s / commit 0.64 s, 16 senders 0.31 / 1.73 / 0.65 s (predicted 1.2 / 2.2 s — better); 600×4 = 3,868.5 tx/s
  (+12 % over 600×16!), land 0.88 s, seen 3.22 s, 18,544 in flight (77 % of cap); -32603 before the kill = 0 across all 10 generators (bench 4 lost two); v05 caught up in 1,365 s (bench 4 2,160).
  SURPRISES → D3 candidates: (1) validators LESS busy (CPU 18 % vs 33 %) but the telcoin process wrote 498.7 vs 131.6 MiB/s, PSI io 31-34 % vs 10-17 % — IO-bound? (A4n asked); (2) generators 04 Tokyo /
  08 Hong Kong / 10 Mumbai landed NOTHING for 802 / 853 / 491 s before the kill, no RPC error, all resumed 7-13 s AFTER the kill — the same three the certification pass flagged (A2 asked: far-validator
  starvation under load, relieved when the committee dropped to 9 voters?); (3) seen−land 21-35 s on generators 01/03/05 (execution behind on the slow executors); (4) at LIGHT load London (02) and
  Netherlands (06) land at p50 11-17 s in synchronized bursts while the rest land in 0.12-0.84 s (A6 asked); (5) epoch-7 boundary gap 24 s (bench 4 13 s); land p99 402.6 s from the stalls.
- I-A DONE (tasks/issues/bench5-execution-behind-vote-starvation.md): the starvation is an F1-1 SIDE EFFECT exposed at vote time, not an F3-6 regression — proposer names its own newest block (proposer.rs:379);
  F1-1 let executed tips spread 1-6 outputs (≈ 25 blocks each at saturation; 3.65 s measured); a header lives one round ≈ 0.86 s (certifier cancels on the next header, certifier.rs:818); the middle tier
  reached the block 3.0-3.9 s after the proposal (v04 round 1073: proposed 17:44:59.950 naming 21772, cancelled 17:45:01.349; v02 executed 21772 at 17:45:03.813); seven slower nodes = a quorum → every round
  moved on. Dropping F3-6 (5-s wait) would still vote after the cancel; retries already exist (250 ms × 6 + certifier backoff). Per-author lock held across the wait → refusals queue 1/s (v01 lock 7.3-8.5 s).
  FIX (design D, proposer-only, no fork gate, cherry-pickable): name the (2f+1)-th highest block among own tip + parents' blocks (never above own tip, ≤ 8 outputs below, own hash); companion V (voter): wait
  before the lock, refuse stale requests at once. 'Vote while behind' rejected as unsafe (the subscriber fork check assumes f+1 honest voters verified the block). Fields: ≥ 98 % own-header certification per
  node, no generator silent > 30 s, ≤ f behind-refusals per header. Keep F3-6. The brief's earlier 'F3-6 regression' wording is superseded by this.
- D3 TRIAGE DONE (benchmark/private/bench5-r20261107-1504/D3/triage.md): SYSTEMIC (investigators launched): (1) accepted txs silently dropped until the generator's 300-s resend (1.85 % of sampled
  landings ≥ 300 s, none in 250-300 s, 8 of 10 generators; 53 % with a nonce skip first) + duplicate inclusion of the resends (37,683 `nonce too low` skips per node in outputs 12084-12091 at 17:55:01-20Z;
  v04 re-sealed byte-identical batches every 300 s → 5 digests committed/executed 2-3×; no dedupe between seal and execution) → bench5-sealed-tx-invisible-drops-and-duplicates (I-D); (2) loaded epoch
  boundary drain (close waits for the 7th executor; gaps 22.6 / 11.0 s; records at exactly 7/10; ≈ 1,400 tn::tasks capacity errors on v01/v03/v05 at late entry) → bench5-loaded-epoch-boundary-drain (I-E);
  (3) execution lag feeds itself (`finish` + signer job cost rise with queue depth; E4's per-queued-output rayon recovery; slow set changes with load, so not hardware) → bench5-execution-lag-feedback (I-F).
  KNOWN: London/NL leader share = certificate inclusion (not election skew); seen−land on 01/03/05 = S7 + S10; bench-4 items closed: Seoul certification (100 %), v05 cold save_blocks, obs-11 disk. NOISE:
  37-round teardown spread, v06 fsync probe, obs-11 'sync exchange failed'. NEEDS DATA: 600×4 vs 600×16 capacity (recut sat4 without the 81 s of cool-down — D42), v09's 3 not-found leader rounds, RSS
  growth 6.3-8.5 GB after the restart, whether bench 3/4 had the 300-s cliff.
- A2 DONE (benchmark/private/bench5-r20261107-1504/A2/certification.md §"Far-validator starvation under load", vote-path.md, numbers.json): own-header certification in load_all10 — v04 Tokyo 0.2 %, v08 Hong Kong
  0.0 %, v10 Mumbai 16.3 %, the other seven 99.7-100 % (idle/light/600×4 all ≈ 100 %). MECHANISM = F3-6 REGRESSION: the voter waits ≤ 1 s for its own execution to reach the header's execution block, then
  refuses `ExecutionBehind`; v04/v08/v10 were the FASTEST executors (exec lag 6.4-9.1 rounds vs 12.6-13.5 middle, 22-31 for v01/v03/v05), so their headers named blocks the others had not executed → seven
  voters refused each header 537-683× with exec_wait_ms 1000-1001 (cites v04:17:45:01.228Z header block 21772 local 21719; v02:17:45:00.354Z `vote path timing … outcome=behind exec_wait_ms=1001`), the
  other seven certificates are exactly the quorum of 7 so every round moved on and cancelled their headers (v04 916 of 918 rounds); no own certificate for 787 / 817 (+226) / 487 s = A1's landing gaps within
  1-36 s; batches not lost but cycled (≈ 20 digests through 296-368 headers, 560-640 s to commit); their workers nearly stopped sealing (94 / 31 / 126 batches vs 889-2,089). At the kill (9 alive) at most two
  certificates per round can be missing and the slow tier (v01+v03: 14,082 refusals post-restart) was refusing nearly everything, so rounds waited for a fast node's certificate → the three certified again
  7-13 s after the kill and then took turns dropping (v04 18:00-18:03, v08 18:05-18:09). `votes_refused_execution_behind_total` over the run: v01 14,802, v03 11,969, v05 5,747, v06 3,171, v09 2,728, v07 2,559,
  v02 2,558, v10 2,222, v04 1,317, v08 588 (0 at idle/light); `votes_refused_inactive_total` only v05 (31,577) ✓; vote_timeouts 0 everywhere ✓. L7: `digests resent … cause=canceled` landed in the next header
  2,811 of 2,813 times (v04 8,162 / v08 7,479 / v10 3,543 requeues) — useless on starved nodes (the next header is refused for the same reason). Proposer reasons: 100 % min_delay idle/light; loaded 90-97 %
  min_delay on the seven, while 1,612 of 1,911 `parents_and_threshold` proposals came from the three starved nodes (re-queued digests kept them at the threshold). LONDON/NETHERLANDS at light load = an OLDER
  mechanism: their headers certify (99.5 %) but only 13-18 % of their certificates are committed; the batches wait for the periodic "undelivered headers" resend every ~20 s (same ms on both nodes,
  v02:16:18:09.329Z / v06:16:18:09.339Z from_round=373→419); first proposal → commit p50 13.9 s (light8) / 27 s (light16); at 600×4 and above 76-99.7 % commit.
- A4n DONE (benchmark/private/bench5-r20261107-1504/A4n/f2-verdict.md §0 = the regression mechanism, bottlenecks.md, census.md/json, f2.json, buckets-5min.json, v05-catchup.json): at saturation the task costs
  288.6 µs/tx (bench 4: 215; +34 %) = execute 87.4 (−47 %: recover_wait 0, evm 26.5, root 49.2, finish 11.4, dumps 0.2-0.3) + persist 199.2 (×4: save_blocks 21.1, MDBX commit 178.0); 1/288.6 µs = 3,465 tx/s
  = A1's 3,449. E1 CONFIRMED (log 5.05 MB/min vs 1,163), E2 CONFIRMED (root 56 % of execute → parallel state root = the bench-6 execute item, worth ≤ 49 µs/tx), E3 CONFIRMED but the 64-slot backlog does not
  exist (channel depth ≤ 2; consensus commits at the execution rate 0.573 vs 0.559 outputs/s), E4 CONFIRMED (recover_wait 0.0-0.6 µs/tx loaded; the job runs off-thread, 13-21 µs/tx), E5 inconclusive by
  construction (shipped with E1/E4; the combined −78 µs/tx is at the top of the 23-79 expectation). CEILING REGRESSED THROUGH PERSIST: the MDBX commit fsync is 1.03-1.06 s per output on every node
  (bench 4: 0.30-0.34 s) with IDENTICAL logical writes per tx (table growth 73/33/47 B/tx, 0.44 accounts + 0.62 slots per tx in both runs) but ≈ 4.3× the device bytes per tx (155 vs 36 KB; write ops 227 vs
  32 KB; ≈ 0.9 GB per output vs 0.32) — the disk is no slower (same hyperdisk-balanced 20k IOPS / 800 MiB/s, same debian-12 family, same tn-node-deployment ref d9446f7); writes sustained ≈ 470-530 MB/s with
  per-minute peaks at the 800 MiB/s cap; PSI io 26.5-27.2 %; CPU 17-19 %. Bench 3 (r20261103-1922) shows bench 5's pattern (438 MB/s, 231 KB ops); bench 4 is the OUTLIER. Cause below the engine (OS /
  storage layer); the one thing bench 4 had and bench 5 lacks is the 1.16 GB/min debug log on the same volume (untested). Not settled from this run → D3 investigation + bench-6 checks (record kernel, mount,
  vm.dirty_*, THP in the pre-start probe; iostat; one short arm on the bench-4 image). Slow executors v01/v03/v05: 94-97 µs/tx vs 84-88, all in `finish` (17-19 vs 10-12) and the signer job (19-21 vs 13),
  persist identical — 2-3 % slower than the commit rate so their backlog grows (9-13 s of the 21-35 s seen−land gap); why `finish` is slower there is open. v05 catch-up: 0.49 outputs/s executed vs 0.437/s
  committed → net ≈ 0.1 output/s; gap 158 → 56 outputs by 18:21, head reached 18:22 after the load stopped. CENSUS: warn+error 77,168 (bench 4: 266,118); TooNew vote storm gone (12 vs 100,852); 0 panics /
  DB errors; NEW ≈ 1,400 tn::tasks `Failed to track spawned task … no available capacity` (1,248 in the chaos window at the loaded epoch-8 boundary); NEW 414,513 `skipping invalid transaction: nonce too
  low` (37,683 per node) at the same boundary (duplicate txs?) → D3; leader share v02/v06 198/193 of 12,834 leader rounds (lowest two in bench 4 as well); batch-serve pool full 0; open-phase sheds 6,675 all
  after the epoch-8 boundary. v06's slow fsync probe does not predict its persist (commit p50 1,079 vs 1,069-1,081 ms fleet; r = 0.10).
- A6 DONE (benchmark/private/bench5-r20261107-1504/A6/stages.md, stages-<window>.json, landings.md, levers.md, littles-law.json; windows cut from the blasters' REAL phases): floor pooled ts 0.65-0.67 s,
  commit 1.25-1.27 s, seen 1.50-1.51 s at 8/16 senders (predicted 1.2 / 2.2 s → 0.5-0.7 s better); sanity Σ−seen ≤ 250 ms on 100 % (light) / 97-99 % (load) of blocks. Light-load stage p50 (ms): S1 pool 26,
  S2 batch quorum 171, S4 digest wait 155, S5 cert 155, S6a 155, S6b leader-created→commit 611 (40 % of seen; consensus S2-S6b = 82 %), S11x execute 37, S13x visibility 152. Saturation (600×16 pre-kill):
  S1 423, S4 418, S5 396, S6a 750, S6b 1,264, S7 wait-for-execution p95 16.9 s (slow executors LA/Sydney/Ashburn), S10 ENGINE QUEUE 9,566 (64 % of seen 14.87 s), S11x 282; one output 1,658 ms = execute 479
  + persist 1,167 of which MDBX commit 1,035 ms (190 µs/tx) → PERSIST-BOUND (bench 4: execute 75 % / persist 24 %); persist is off the visibility path (blocks hit RPC at execution) and reaches seen only via
  the queue. Little's law holds (ratio 0.97-1.04): 600×4 24k in flight 4,006 tx/s mean seen 4.59 s; 600×16 96k in flight 3,481 tx/s mean 23.69 s — 4× in-flight = −13 % throughput, 5.2× latency.
  FINDINGS → D3: (i) London (v02) and Netherlands (v06) at light load: only 18 % of their certified headers ever COMMITTED; the rest are orphaned and re-sent on a synchronized ~60-round (~20 s) cycle →
  their generators' p50 14.5-18.7 s vs 1.3-2.0 s elsewhere (far-validator certificate inclusion; #1781 territory); (ii) pre-kill Tokyo/HK/Mumbai certified only 52 / 40 / 271 of 1,041 headers: voters answered
  `outcome=behind` (F3-6 execution-behind refusal; exec_wait 1 s, lock ≈ 8.5 s) → 0 tx landed 17:42-17:54Z (Tokyo, HK), 17:44-17:53Z (Mumbai) — the F3-6 commit × 3 slow executors starved them (A2 confirms).
  LEVERS (levers.md, 13 with arithmetic): 1 bound in-flight at the node by the execution backlog (seen p50 14.9 → 3.2-4.7 s at saturation; no new capacity); 2 pipelined persist (×1.42 throughput, p50 −4.4 s);
  3 far-validator orphan re-send / inclusion (−10 to −16 s for London/NL at light load — largest light-load p95 lever); 4 fix the execution-behind refusal starvation; 5 #532 fast direct commit (S6b −0.15-0.35 s
  light); then #552 multi-anchor p95 −0.35 s; min_header_delay 250 + threshold 1 only −0.19 s p50 (headers are 100 % min_delay, threshold 5 never fires) and must follow lever 3; overlap batch quorum −0.1-0.15 s;
  L6 batch-wake already in (−0.07-0.10 s, 66-76 % wake=arrival, S1 26-31 ms); max_batch_delay 100 ≈ 0 (drop the arm); L7 +113-118 ms per re-queued digest vs a 20-45 s fallback, no p50 effect; per-type latency flat.
- A3 DONE (benchmark/private/bench5-r20261107-1504/A3/verdicts.md, recovery.md, recovery.json, boundary.md): F1 CONFIRMED on every field (outside_gc_window demotions on healthy nodes 0 vs 2;
  consensus_exec_lag_rounds max v01 62 / v03 54 / v09 58 with no demotion; commit_lag_rounds p99 ≤ 5 loaded, 6.12 in the chaos window; run-ahead blocked 0; CvvActive 10 until the kill; -32603 before
  the kill 0); F3 CONFIRMED (v05: 1 rejoin vs 13; no restart_gap line (store−pack 30 rounds); primed primary_round ≥ newest_round on all 133 lines; first own cert 1.85 s after promotion; 8 stuck-replay
  re-requests, 43 stalled-head lines all head_age with the replay moving; votes_refused_inactive 31,561 on v05 only); kill → CvvActive 28 min = INCONCLUSIVE (execution-bound catch-up). NEW WATCH
  ITEMS for D3: v01 and v03 are the slow executors (not slow-fsync v06) — they reach loaded epoch closes 11-27 s late, never voted the epoch-7/8 records (formed at exactly 7/10), and after the kill
  refused 14,785 / 11,953 votes as execution-behind → every remaining voter was on the critical path, commit gaps 4-15 s 18:16-18:21Z; loaded epoch closes wait for execution (22.6 s commit gap at
  the epoch-7 close); the teardown's 37-round idle spread is a scrape-timing artifact. A4n owns why v01/v03 execute slower.
- A4o DONE (benchmark/private/bench5-r20261107-1504/A4o/): whole run 4h12m34s (bench 4: 9h16m05s); teardown 35 min in one attempt (bench 4: 6h58m, five attempts); defects D36-D48
  (D36 create path aborts on any gcloud client crash — third run in a row with this fault class; D42 the planned manifest.phases feed the stall scan and certification windows → a false
  90-s 'commit stall' at the end of the load and a mixed window 77 s off — A2/A3/A6 use the blasters' REAL phase timestamps, not manifest.phases).
- Interventions: none on the fleet. Orchestrator actions = the documented resume (fund+run index 4) and step 15 by hand. No SEC-2 restart was needed
  (commits continued with 9 voters while validator-05 was inactive — verify in A3).
- Light-blast dirs: `blast-{0,1,2}-*/` (floor + Little's-law point), `blast-3-*/` (aborted partial, exclude from KPIs, keep for A4o), `blasters/` (index 4 =
  the headline load blast), `funder-{0,1,2,3}-*/` + `funder/`. manifest.blasts[] = indices 0-2 rc 0 + index 3 rc 1; index 4 is manifest .blast only
  (light_stop note: pass the light dirs explicitly with `--floor-blast-dir` / `--blast-dir` where the tooling asks).
- Comparators: r20261105-0803 (bench 4, 4,578 tx/s, seen p50 12.9 s, ts p50 3.3 s; F1 two healthy demotions; F3 loop), r20261103-1922 (bench 3),
  r20261007-0316, r20261006-0458.
- Teardown `--run r20261107-1504 --yes` 18:42:00-19:17:24Z rc=0: health table (Prometheus, before any delete) all 10 validators cvv_active, observer-11 observer, failed batch reports 0,
  epoch 10 rounds v01 1137 … v09 1100 / v10 1101 (a 37-round spread at idle — A3); node logs pulled 18:43:54-18:48:54Z (3 files per node: current container log, 1 saved log, unit
  stdout; validator-05 and observer-11 have a 4th = the pre-kill / pre-restart container log), unit-stdout total ≈ 1.87 GB for 11 nodes (bench 4: ≈ 49 GB per validator);
  certification (informational, analysis/certification.json): v04 Tokyo 49.6 %, v08 Hong Kong 44.4 %, v10 Mumbai 67.9 % of own headers certified in the mixed phase (snapshots
  logs/bench-validator-{04,08,10}-telcoin-cert-fail-*.log.gz) — A2 owns the why (bench 4: Seoul 68.5 %); Prometheus TSDB snapshot logs/bench-obs-prometheus-20261107T185712Z.tar.gz
  (20 MB); provenance ok (sha 067639def, forks subsecond-from-genesis on every node); INDEX.md + CHECKSUMS.sha256 804 files 2,640,856,510 bytes; TEARDOWN_DONE deleted=12 left=0;
  obs-devnet untouched. The results dir is the ONLY full copy until archived (GCS archive is a Wave E step).

## Units (Wave D1 in parallel: A1, A2, A3, A4n, A4o, A6; then D2: P, A5; then D3: triage → investigators)
- A1 KPIs: the bench-4 driver (A1/kpi_driver.py; validate on r20261105-0803 first) + the bench-5 additions: `seen_ms` per phase, the light-load
  windows (indices 0-1: floor KPIs `floor_time_to_land_p50_s`, `floor_time_to_seen_p50_s` via `kpis.py --blast-dir`), index 2 (600 × 4) as the
  Little's-law point (in-flight ÷ throughput vs measured p50), bias-corrected `time_to_commit` (commit_timestamp_ms − submit), per-generator
  landing set over time (the F1 proof from the user side: did every generator keep landing until the kill? `-32603 validator is inactive` count
  = 0 before the kill is the field). Outputs A1/bundle_windows.json, bundle_kpis.json, kpis.md, light.md.
- A2 certification + vote path: cert-rate per phase (official tools), `vote path timing` per stage/pair/phase incl. `outcome=behind` counts
  (F3-6), `vote refused` (inactive / execution-behind) per node, certifier `request vote … attempt elapsed_ms`, header_age, reqres class
  durations; the far-validator certification share (Seoul 68.5 % in bench 4) with and without L7 re-queue; `header uncertified reason`
  counts per node (canceled vs no_certificate) and `digests re-queued`. Outputs A2/numbers.json, certification.md, vote-path.md.
- A3 recovery + boundary = **the F1 and F3 verdicts** (design §F1/§F3 "Bench-5 fields", §SEC expectations): per non-chaos node
  `tn_node_mode_transitions_total{to="cvv_inactive",reason="outside_gc_window"}` = 0; `consensus_exec_lag_rounds` max per node (> 40 on the
  slow nodes proves F1-1 bit); `commit_lag_rounds` p99 ≤ 6 outside the chaos window; `commit_run_ahead_blocked_total` = 0; `we are behind`
  count; committee size 10 until the kill; `epoch_behind` at boundaries (expected on the slowest node at the first boundary after the kill —
  report, do not hide); the chaos node (validator-05): kill → `cvv_active` ≤ 2 min, `rejoin` transitions per episode = 1, `dag restored
  num_certs` (recorded), `primed consensus rounds primary_round >= newest_round`, no genesis-parent header above round 1, `rejoin_grace_holds_
  total` = 0, `attempts_exhausted` = 0, `inactive_certificates_cached_total` > 0 while inactive, `rejoin_blocked_total{reason}` time series,
  no `Fetch task failed … missing parents` after a promotion, `certificate committed` on the promoted node within 30 s; `restart_gap`:
  expectation 0 on every node and a MISSING `restart_gap` is NOT a failure; > 0 = a real SEC-3 hole → report `hole_round`; `re-requesting
  consensus outputs behind the gossiped frontier` lines = the stuck-replay recovery (fine, count them + backoff_ms); `stalled head not ready`
  with `replayed_number` frozen > 10 s while `newest_number` climbs = stuck follower (DEFECT); SEC-2 occurrences (commits stalled with
  inactive members; the runbook restart) if any; observer-11 restart; `epoch record quorum … missing=[…]` at every boundary; loaded
  boundary wait; commit drift per node per minute (`subdag committed` leader_round vs the fleet). Outputs A3/recovery.md, recovery.json,
  boundary.md, verdicts.md (one line per field: value, expectation, verdict confirmed / inconclusive / regressed, cite).
- A4n node census + **F2**: warn/error template census per phase (new templates vs bench 4); the execute split per 5-min bucket per node from
  `output executed` (recover/evm/root/finish/other ms ÷ txs → µs/tx; `max_block_root_ms`), `forward_wait_ms` + `queue_wait_ms` + channel depth
  (the 64-slot backlog bench 4 could not see), persist split (`persisted output` save_blocks/markers/commit + reth `_mdbx`/`_sf` histograms)
  vs the fsync probe per node, engine busy, µs/tx vs bench 4's 215 (execute 165 / persist ~50): how much did E1 (dumps), E4 (signer off-thread:
  `recover_wait_ms` ≈ 0?), E5 (cached reads) buy; `root_ms/txs` → is the parallel state root the bench-6 item; leader share
  (`scheduled leader … swapped found`, tn_primary_leader_rounds_total); `batch-serve pool is full`; LOG_RATE vs bench 4's 1.16 GB/min;
  resources (metrics.json, sampler, PSI, disk throttle). Outputs A4n/census.json, census.md, bottlenecks.md, f2-verdict.md.
- A4o operational friction: timeline (deploy/idle/blast ×4/collect/teardown wall-clock vs bench 4), faults (IAP retries, stockouts, reauth),
  defects (the harness: fsync probe, LOG_RATE, light-load sequencing, landings export, D34/B9 fixes — did they behave?), interventions,
  recommendations for bench 6. Inputs: tasks/bench5-live-r20261107-1504-*.log, tasks/checkpoint-bench5-live.md (gitignored, read-only),
  results/<run>/logs/deploy-*.log, tunnel.log, chaos-remote.log, the teardown log(s). Outputs A4o/timeline.md, faults.md, defects.md,
  interventions.md, recommendations.md.
- A6 land-path decomposition (**the user's top protocol priority**): run `benchmark/tools/stage-latency.py` per window (idle, light8, light16,
  load600x4, load_all10 — drop epoch boundaries ± 30 s from the light windows) on one node first, then all ten; per-stage p50/p95 S0-S13 and
  the three headline sums (`ts`, `commit`, `seen`) with the sanity check Σ stages − seen ≤ 250 ms; the floor (light) vs saturation split; per
  generator and pooled; the landings sample (`landings-*.ndjson.gz`) for per-type and over-time latency; batch build reasons / pool age (L1),
  digest wait + header reasons (L3), uncertified headers and re-queued digests (L7), `batch-wake` effect on S1 (pool age p50 vs bench 4's
  ~125 ms), quorum_ms / report_ms (L2), fetch_ms / pack_persist_ms (L4), forward/queue wait (E3), execute/persist (E2). Then RE-RANK the
  levers of design §LAND with measured stage times and the arithmetic of each proposal (what each would remove from p50 and p95 at light load
  and at saturation): L6/L7 (measured now), parameter arms (max_batch_delay 100, threshold 1, min_header_delay 250), pipelined persist +
  parallel root (throughput → latency at saturation), #532 fast direct commit, #552 multi-anchor. Outputs A6/stages-<window>.json, stages.md,
  levers.md (the ranked list, each with its measured basis), landings.md. Split A6a (stage tables) / A6b (levers) if the budget trends high.
- P backfill (after A1/A2/A4n): benchmark/report/backfill/2026-11-07-main-fixes.json in the schema of 2026-11-05-main-v1lazy-obs.json
  (methodology + caveats: fix build, light-load arm, `seen_ms` added, bias correction, durable fsync, obs via bench-obs); validate with
  make_bundle.load_backfill and the scrub/hygiene scans; notes in P/backfill-notes.md.
- A5 report (after all): tasks/bench5-report-r20261107-1504.md in the bench-4 report's structure (§1 summary, §2 run facts/provenance, §3 KPIs
  vs r20261105-0803 and the earlier runs incl. the new seen/floor KPIs and the stage table, §4 findings ranked — the F1/F3/F2 verdicts first,
  then the land-path decomposition and the re-ranked levers, then anything new, §5 friction, §6 next runs = bench 6 arms, §7 evidence index
  with `<inst>:<ts>` cites), plus a `## r20261107-1504` section in benchmark/private/followups.md. No IPs, ids, project names, bucket names or
  home paths (test_report_scrub rules); numbers only from A1-A6 with the file cited. Human-writing skill applies.
- D3 triage (after D1): one agent reads A1-A6 + the bench-4 watch items (v09's not-found leader rounds; Seoul's certification share; the
  13-s loaded boundary gap; v05's cold save_blocks; the epoch-record collector that never retries; observer-11's disk signature) and lists
  candidate systemic findings with evidence; the orchestrator confirms which are systemic (reproducible across nodes or runs, with a
  mechanism); one investigation agent per confirmed candidate writes tasks/issues/bench5-<slug>.md in the D-I shape with a bench-6 proposal.
