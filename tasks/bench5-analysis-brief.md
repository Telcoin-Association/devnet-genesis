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
- Deploy `--yes --with-contracts --to 12` 15:04:50-15:50:54Z rc=0: coordinated start due 1794065010 (15:50:10Z? no — see manifest.coordinated_start) 11/11 started spread 0 s;
  fsync probe median 986 µs, slow=[bench-validator-06] 1253 µs; OBS_STACK_OK 20 s, OBS_READY 47 s; fleet ready 10/10 CvvActive at the first pass; OBSCFG_OK ×11
  restarted=none; POSTCFG_OK ×11 sha 067639def forks subsecond-from-genesis params 1000/350/250 thr 5; ADM_OK ×11 denied 0/0; contracts deployed; bucket
  gs://tn-devnet-bench-r20261107-1504. Idle 15:50:54-16:01:58Z.
- Blast segment `--yes --from 13 --to 15` from 16:01:58Z: step 13 fund ×4 (indices 0-3, BENCH_FUND_DONE rc=0 each); step 14 light sequence:
  index 0 (8 senders × window 16, 60/360/60 s, chaos off) LIGHT_LOAD_START ~16:11Z, blasters start ~16:16Z, all BENCH_BLAST_DONE 16:27:14Z, archive
  `blast-0-20261107T163112Z/`, LIGHT_LOAD_DONE rc=0; index 1 (16 × 16) 16:31Z → 16:47:12Z, `blast-1-20261107T165107Z/`, rc=0; index 2 (600 × window 4)
  16:48Z → 17:08:04Z, `blast-2-20261107T171309Z/`, rc=0. LOG_RATE bench-validator-01: blast 0 8.2, blast 1 8.4, blast 2 (saturation) 10.8 MB/min
  (bench 4: 1,160 MB/min). Index 3 (the configured profile) ABORTED: `gcloud compute instances create bench-blaster-06` crashed client-side
  (ReadTimeout 300 s; logs/create-bench-blaster-06.log); 9 blasters had started at 17:17:36Z and sent for ~2.5 min before the driver's exit cleanup
  stopped them (manifest copy + partial outputs in `blast-3-20261107T173343Z/`, abort reason=interrupted 17:20:07Z); the chaos had NOT fired. Sequence
  rc=1 at 17:29:10Z (BENCH_DEPLOY_RESULT rc=1 last_step=14). A4o: harness defect — one transient gcloud client timeout on a blaster create aborts the blast.
- Resume per the driver's printed instruction: `BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=4 benchmark-blast.sh fund` 17:30:25-17:32:50Z rc=0 (funder-3-20261107T173046Z/
  holds the index-3 funder copy), then `run` 17:32:50Z: 10 blasters × 600 senders @ 400000+, window 16, start_at 17:38:02Z (mixed 17:40:02-18:20:02Z,
  cool-down to 18:23Z); chaos against epoch 7 (opened 17:35:43Z): kill -9 bench-validator-05 17:54:44Z rc=0 (59 s before the 17:55:43Z close; pre-kill
  container log saved on the node as /var/lib/bench-logs/telcoin-pre-kill-20261107T175417Z.log.gz), systemctl start 17:59:44Z rc=0, observer-11 systemctl
  restart 18:04:44Z rc=0; validator-05 polled cvv_inactive from its restart through the end of the load (last driver poll ~18:25Z); BENCH_BLAST_DONE ×10
  rc=0 (blaster-05 first — its node was inactive), all reported 18:25:57Z; `blasters/` = index 4 (manifest .blast.run_index 4, chaos 3 entries, abort null);
  run rc=0 18:30:14Z. Epochs 1200 s: epoch 8 17:55:43-18:15:43Z, epoch 9 18:15:43-18:35:43Z.
- Step 15 (`--from 15 --to 15`, BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=4) 18:31:13-18:41:19Z rc=0: collect ok; rejoin wait found validator-05 CvvActive at the
  first poll (~18:33Z → it rejoined MID-EPOCH 9, between 18:25Z and 18:33Z, within ~10 min of the load ending; bench 4's chaos node needed the next
  boundary, 36 min); prom_window 15:40:20Z → 18:39:18Z end_reason=fleet_ready (waited 253 s); collector: metrics.json 111 MB, 21 instances, 307 GCP series,
  prometheus missing=0 absent=0 errors=0. Certification deferred to the teardown's log pull.
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
