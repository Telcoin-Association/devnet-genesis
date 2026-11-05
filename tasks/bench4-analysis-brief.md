# Bench 4 analysis brief — run r20261105-0803 (written 2026-11-05T10:23:42Z, orchestrator)

Repo /home/drtnarg/coding/telcoin/devnet-genesis (main @ d6a8d53 + the run's results, untracked under benchmark/results/r20261105-0803/ — gitignored).
Rules: tasks/bench4-agent-rules.md HARD RULES apply (no git add/commit/push; no fleet contact — the fleet is DELETED, every input is local;
one writer per output dir; budget < 250k tokens; checkpoint tasks/checkpoint-bench4-<unit>.md rewritten after each section; hand back a
summary). Outputs under benchmark/private/bench4-r20261105-0803/<unit>/ (gitignored, private: real IPs/ids allowed there, never in tasks/ or the
report). Scratch (bulky copies) under /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/2172e6fa-38c4-4090-b14a-edafee5892b3/scratchpad/<unit>/.
Templates = the bench-3 units' outputs and scripts under benchmark/private/bench3-r20261103-1922/{A1,A2,A3,A4n,A4o,P}/ and their
checkpoints tasks/checkpoint-bench3-{A1,A2,A3,A4n,A4o,A5,P}.md; the bench-3 report tasks/bench3-report-r20261103-1922.md; the frozen
design tasks/checkpoint-bench4-design.md (D2 = the eight observability questions Q1-Q8 and the "Analysis contract" = the exact log
line shapes and Prometheus series the bench-4 image emits; D5 = the run profile). Reuse the bench-3 drivers where they fit (A1's
kpi_driver.py reproduces the published KPIs of 0316/0458/1922 — validate on one of them first).

## Run facts (cite, do not re-derive; everything else is in benchmark/results/r20261105-0803/manifest.json and metrics.json)
- Image adiri @sha256:f6922184… = branch bench/main-v1lazy-obs-2026-11 (origin/main a0d6e6e26 + PR 1783 V1Lazy + 8 observability
  commits), node sha 496ebefb52627fcf20f4074b58d7b3309b8b4bb8, forks subsecond-from-genesis, chain 32286, v2 nodes, trust-everywhere
  (ADM denied 0/0 on all 11). txgen blast-v2-3911723 (collector from 4434bac). Fleet: 10 validators + observer-11 in ten regions
  (validator-05 us-east4-b), c3-highcpu-8; log filter info,primary=debug,engine=debug,subscriber=debug,worker::network=debug,
  network::reqres=debug (+3 =info overrides), logrotate 20G; metrics via the run's own bench-obs VM (Prometheus snapshot in
  logs/bench-obs-prometheus-*.tar.gz if the teardown pulled it; metrics.json has 236 Prometheus series + GCP); obs-devnet untouched.
- Timeline (UTC): coordinated start 08:22:35 (due 1793866955, 11/11 START_AT began=due, spread 0 s; manifest.coordinated_start.ts 08:30:13 is the record's write time — A4o D31); nodes healthy 08:37:58; contracts 08:49:03; deploy
  --to 12 done 08:49:09; idle to 09:00:30; fund 09:01:37-09:03:03; blasters created 09:03:54-09:04:28, start_at 09:08:29, BENCH_BLAST_DONE 09:53:12 (BENCH_DURATION_SECS=2400, warmup/cooldown per
  config.sh); chaos: kill -9 validator-05 09:33:50 (planned, drift 0; 59 s before the epoch-3 close at 09:34:49), start 09:38:50,
  observer-11 systemctl restart 09:43:50 (pre-restart container log saved on the node); step 15 rejoin wait 886 s (validator-07
  CvvInactive by committee rotation) to the 10:14:50 boundary + 90 s settle + 180 s confirm → prom_window 08:37:58-10:20:29
  end_reason=fleet_ready; epoch duration 1200 s; 0 aborts; all 10 blasters BENCH_BLAST_DONE rc=0.
- Comparators: r20261103-1922 (bench 3, v0.2.0-devnet 3f9b0709, Closed admission, 4,037 tx/s), r20261007-0316, r20261006-0458
  (published at benchmark.telcoin.network; canonical copies in gs://tn-devnet-benchmark-archive and benchmark/results/ if present).

## WARNING from A4o (D23): the unit logs are huge. Under load `engine=debug` wrote ≈ 1.16 GB/min per validator: 57 % `block executed`
(a Debug dump of the whole ExecutedBlock, ≈ 716 kB per line) and 19 % `executing output` (the whole ConsensusOutput, ≈ 18.7 MB per line),
plus per-tx `governance collects` / `allocating basefees`. Each validator's unit log is ≈ 49 GB uncompressed (idle 7.3 MB/min). NEVER cat
or zcat a whole file into a tool: stream with `zcat … | grep -E 'target=…|<message>'` (or awk on the target field) and drop
`target=engine` lines except the three contract messages (`output execution task finished`, `output executed`, `persisted output`).
Budget your reads; one node first, then the rest with the same script. A4o's byte census is in its scratchpad (target-volume.txt).
OPEN QUESTION (A1 vs the brief): validator-08 went cvv_inactive at 09:20:13Z and validator-07 at 09:27:13Z (tn_node_mode), both
MID-EPOCH (epoch 3 = 09:14:49-09:34:50Z) and before the 09:33:50 kill — so NOT committee rotation (the brief's step-15 note was wrong):
v07 was promoted 13 times (12 fell back) and held active only from 10:15:13Z; v08 held from 09:54:58Z; v05 (chaos) inactive 09:39:13Z,
7 promotions, active from 10:15:13Z. Their generators stopped landing (`-32603 validator is inactive`) at 09:20:12Z / 09:27:05Z.
A3 owns the why (bench-3 F3 promote/demote loop? `we are behind` / `rejoin not ready reason=`), A4n the resource side (did they
saturate first?), A2 the vote-path side (were their votes late before the drop?). A1 results: benchmark/private/bench4-r20261105-0803/A1/
(headline 4,578 tx/s all-generators, +13.4 % vs 1922; rounds 0.8 → 1.5 s under load; chain tps held as the landing set shrank 10→7).

## Units (parallel: A1, A2, A3, A4n, A4o; then P and A5)
- A1 KPIs: the 13 KPIs + windows for r20261105-0803 with the bench-3 driver; comparison table vs 1922/0316/0458; rounds/s per window; per-generator
  landing. Outputs A1/bundle_windows.json, A1/bundle_kpis.json, A1/kpis.md.
- A2 certification + vote path (Q1 voter wait, Q2 proposer side, Q8 V1Lazy effect): cert-rate per phase (official tools), C/round period
  (propose-latency), the NEW `vote path timing` lines → per-stage breakdown (lock/validate/exec_wait/parents/lead/batches/store/persist)
  per pair and per phase, `vote timeout fired` stages, `vote refused: header too new`, certifier `request vote … attempt elapsed_ms`,
  `vote requests issued … header_age_ms`, `header stored and sent`, network::reqres class durations and `tn_network_outbound_request_
  duration_seconds{class}` — is the vote still two RTTs (bench 3 F2) under V1Lazy? Outputs A2/numbers.json, certification.md, vote-path.md.
- A3 recovery + boundary (Q5 rejoin loop, Q7 epoch quorum): chaos timeline vs plan; validator-05's path through `rejoin not ready … reason`,
  `attempting to rejoin`, `we are behind`, `dag restored`, `reproposing header`, mode transitions (tn_node_mode_transitions_total{to,reason},
  tn_executor_rejoin_blocked_total{reason}); does the bench-3 F3 promotion/demotion loop recur and why; observer-11 restart; `epoch record
  quorum … missing=[…]` at every boundary; loaded boundary wait (bench-3 F6). Outputs A3/recovery.md, recovery.json, boundary.md.
- A4n node census (Q3 leader share, Q4 execution/persist, Q6 batch starvation): warn/error template census per phase; `scheduled leader …
  swapped found` share per validator + tn_primary_leader_rounds_total/leader_commits_total; execution split from `output execution task
  finished queue_wait_ms task_ms`, `output executed … execute_ms persist_ms announce_ms`, `persisted output … save_blocks_ms markers_ms
  commit_ms` + engine/reth Prometheus series (bench-3 F1: is persist still the growing part?); `batch-serve pool is full … tier` and
  tn_worker_sync_serves_denied_total; admission counters; resources (metrics.json, sampler, PSI, disk throttle). Outputs A4n/census.json,
  census.md, bottlenecks.md.
- A4o operational friction: timeline (deploy/idle/blast/collect/teardown wall-clock vs bench 3), faults (IAP retries, stockouts, reauth),
  defects, interventions, recommendations — INCLUDING the obs-devnet incident (root cause: devnet nodes' DEBUG file logs; D-A/D-B fixes;
  see tasks/checkpoint-bench4-live.md "Wave A-ops") and the three new live findings (v2 guard samples one commit; the in-place driver edit;
  the Loki filename label). Inputs: tasks/bench4-live-r20261105-0803-*.log, tasks/checkpoint-bench4-live.md, results/r20261105-0803/logs/deploy-*.log,
  tunnel.log, chaos-remote.log, the teardown log. Outputs A4o/timeline.md, faults.md, defects.md, interventions.md, recommendations.md.
- P backfill (after A1/A2/A4n): benchmark/report/backfill/2026-11-05-main-v1lazy-obs.json in the schema of
  2026-11-03-v020-devnet-closed.json (methodology + caveats incl. "metrics via bench-obs (own VM); obs-devnet untouched"); validate with
  make_bundle.load_backfill and the scrub/hygiene scans; notes in P/backfill-notes.md.
- A5 report (after all): tasks/bench4-report-r20261105-0803.md in the bench-3 report's structure (§1 summary, §2 run facts/provenance, §3 KPIs vs
  the three runs, §4 findings F1… ranked, answering Q1-Q8 explicitly, §5 friction incl. the obs-devnet incident + its three fixes, §6 next
  runs, §7 appendix/evidence index with log cites <inst>:<ts>), plus a `## r20261105-0803` section in benchmark/private/followups.md. No IPs,
  ids, project names, bucket names or home paths in the report (test_report_scrub rules); numbers only from A1-A4n with the file cited.
