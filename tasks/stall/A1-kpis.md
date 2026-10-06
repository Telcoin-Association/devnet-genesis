# A1 — KPIs for r20261006-0458 vs r20261006-0053 vs r20260929-1647 blast 0
status: complete (sections 1-5 done)
completed sections: 1, 2, 3, 4, 5
sections: 1 KPI table | 2 generator health | 3 outage | 4 backfill draft | 5 gaps/oddities

## Method
make_bundle.main() run unmodified via a wrapper (scratchpad/A1/scripts/run_bundle.py, `python3 -I`) that
only redirects WORK_ROOT to scratchpad/A1/work and skips node logs (teardown is writing them; so
provenance = "inferred", not "verified"). --out to scratchpad/A1/out/<run>. Invocations:
  --run r20261006-0458 --compare r20261006-0053           (top level = blast index 2)
  --run r20261006-0053 --force                             (top level)
  --run r20260929-1647 --blast-index 0                     (published baseline)
All three passed the harness scan + site scrub.py gates. Analysis tools = tn-transaction-generator
HEAD 9f61303 (bench/aggregate.py etc.); generator image 3644adc in all three.
Sanity: 0053 headline 3,319.6 and 1647 headline 4,177.2 reproduce the published values exactly.

## 1. KPI table

| KPI | 0458 (certfix) | 0053 (6 Oct) | 1647 b0 (29 Sep) | window |
|---|---|---|---|---|
| All-generators mean, tx/s | 3,889.6 | 3,319.6 | 4,177.2 | all-generators |
| Best 60 s, tx/s | 4,737.4 | 5,214.4 | 5,242.8 | all-generators |
| Landed tx | 11,504,996 | 10,763,764 | 13,772,022 | run (whole blast) |
| Blocks/s | 11.52 | 10.75 | 12.74 | merged mixed |
| Time to land p50 / p95, s | 3.38 / 17.98 | 3.17 / 26.07 | 4.04 / 14.36 | run |
| Commit latency p95, s | 5.75 to 6.25 | 4.77 to 4.88 | 4.75 to 4.87 | merged mixed, range over 9 healthy |
| Execution per output, s | 2.05 to 2.10 | 1.76 to 2.01 | 2.41 to 2.63 | merged mixed |
| Disk write p95, MiB/s (busiest) | 484.1 | 529.4 | 471.1 | merged mixed |
| Write IOPS p95 (busiest) | 5,324 | 5,253 | 7,710 | merged mixed |
| CPU p95, % (busiest) | 31.3 | 28.2 | 32.8 | merged mixed |
| RSS p95, GiB (busiest) | 9.60 | 9.43 | 9.79 | merged mixed |
| PSI io max, % | 26.4 to 32.2 | 26.8 to 33.6 | 26.1 to 30.3 | merged mixed |

Window bounds (half-open, UTC):
- 0458: merged 06:07:48–06:57:40 (2,992 s; mean 3,304.5, best 60 s 5,952.9); all-generators 06:17:40–06:47:48 (1,808 s).
- 0053: merged 01:50:16–02:40:09 (2,993 s; mean 3,329.3, best 60 s 7,239.4); all-generators 02:00:09–02:30:16 (1,807 s).
- 1647 b0: merged 17:55:40–18:45:30 (2,990 s); all-generators 18:05:30–18:35:40 (1,810 s).
Split at the kill (all-generators window): 0458 pre-kill 3,921.2 (1,158 s), post-kill 3,833.4 (650 s);
0053 pre-kill 4,180.3 (586 s), post-kill 2,906.5 (1,221 s, includes the 301 s stall).

## 2. Generator health (blasters/*.json + txgen logs)

| blaster | zone | preamble s | 600 s limit? | incomplete senders | mixed start | submitted | landed_own | unlanded_own | RPC errors |
|---|---|---|---|---|---|---|---|---|---|
| 01 | us-west2-a | 11 | no | 0 | 06:07:51 | 1,475,121 | 1,473,624 | 1,497 | known=17,347 |
| 02 | us-west2-a | 11 | no | 0 | 06:07:51 | 1,250,107 | 1,246,869 | 3,238 | known=18,240 |
| 03 | aus-se1-c | 600 | YES | 62 (134 preamble tx unlanded) | 06:17:40 | 239,043 | 229,289 | 9,754 | known=22,333 |
| 04 | aus-se1-c | 161 | no | 0 | 06:10:21 | 401,064 | 391,276 | 9,788 | known=23,995 |
| 05 | na-ne1-b | 8 | no | 0 | 06:07:48 | 1,661,331 | 1,651,504 | 9,827 | known=9,846; conn=0 (92 WARN: scanner rotate / nonce resync failed during outage) |
| 06 | na-ne1-b | 8 | no | 0 | 06:07:48 | 1,886,196 | 1,885,043 | 1,153 | known=16,323 |
| 07 | | 12 | no | 0 | 06:07:52 | 821,638 | 816,699 | 4,939 | known=26,558 |
| 08 | | 11 | no | 0 | 06:07:51 | 894,714 | 890,165 | 4,549 | known=25,423 |
| 09 | | 11 | no | 0 | 06:07:50 | 1,447,560 | 1,444,827 | 2,733 | known=19,101 |
| 10 | | 11 | no | 0 | 06:07:51 | 1,404,549 | 1,401,046 | 3,503 | known=17,808 |
| sum | | | 1 of 10 | | | 11,481,323 | 11,430,342 | 50,981 | |
(submitted = totals.submitted = accepted in every row; "known" = already-known resends. No other error class non-zero.)
Previous run 0053: 8 of 10 hit the 600 s limit (01 59, 02 24, 03 281, 04 600, 07 64, 08 128, 09 64, 10 27
incomplete), only 05/06 ran from 01:50:16; 05 had conn=2,158. Now 1 of 10 (03, 62 incomplete) and
04 needed 161 s; both are the australia-southeast1 blasters. Load per blaster is very uneven (06 1.89 M vs 03 0.24 M).

## 3. The outage (kill 06:36:58.139, restart 06:41:58.179, observer restart 06:46:58.067; all late < 0.18 s)

Chain landed tx/s, 1-minute buckets (combined per-second chain_tx by block timestamp):
06:34 3,932.8 | 06:35 3,275.2 | 06:36 3,085.1 | 06:37 4,033.4 | 06:38 3,539.7 | 06:39 4,355.1 | 06:40 3,898.7 |
06:41 3,928.6 | 06:42 3,625.1 | 06:43 3,417.2 | 06:44 3,674.6 | 06:45 3,642.6 | 06:46 4,001.1
No zero minute. Longest zero-tx run 9 s from 06:38:00 (the epoch-4 boundary, opened 06:37:59). The 06:35-06:36
dip predates the kill and spans blasters 01/04/05/08/10 (not v05-specific). Blaster-05 own landings: 0 from 06:38
to its end (06:47:48).
5-minute blocks (make_bundle tps_5min, aligned to the merged start; the all-generators-aligned ones):
06:17:48 4,155.3 | 06:22:48 3,804.0 | 06:27:48 4,093.9 | 06:32:48 3,614.2 (kill inside) | 06:37:48 3,776.5 (outage) |
06:42:48 3,901.0 (v05 catching up) | tail: 06:47:48 159.6 (1.7 gens) | 06:52:48 54.0 (1.0 gen).
0053 for comparison: 4,299.4 | 3,943.9 | 0.0 (stall) | 3,968.7 | 3,754.5 | 3,868.8.
v05 recovery:
- kpis.recovery: killed 06:36:58, restarted 06:41:58, demoted (first cvv_inactive=1 sample) 06:42:25, rejoined 06:54:55,
  catch_up_secs 750 (0053: null/16 s; 29 Sep b0: 1,500). failed_reports: series absent for v05
  (tn_batch_builder_seal_failures_total{failed_to_report} exists only for v02/v04/v06/v08, 1-2 each) -> effectively 0;
  make_bundle prints "unavailable".
- Prometheus: v05 round 0 / epoch 3 until 06:43:55; committed 1046 (epoch 3) at 06:44:55; epoch 4 at 06:45:55;
  then ~48 rounds/min (v01 ran 40/min under load, 158/min after 06:48); jumped 434 -> 1430 at 06:54:55 (rejoin).
- Sampler (30 s): pid gone 06:37:01; new pid 06:42:01; executed block stuck at 27,969 from 06:42:31 to 06:44:31
  (psi_io ~0), then ~800-870 blocks/min from 06:45:01; gap to v01 ~5,700 blocks held flat while the load ran
  (chain also ~780 blocks/min); v05 reached 36,577 at 06:54:31 only because the chain stopped producing blocks at
  06:48:21. Execution catch-up rate ~= chain block rate under load.
- v05 pool held 8,294 tx (blaster-05's) all through catch-up; cleared at 06:54:55.
Commit cadence (Prometheus, under load): 0458 0.42 subdags/s, 0.90 rounds/s pre-kill; 0.32 / 0.69 during the outage.
0053 pre-kill 0.59 / 1.21. => commit latency p95 5.75-6.25 vs 4.77-4.88; more zero-tx seconds per minute (~32 vs ~27).
The .commit_stalls[] 06:48:31-06:52:04: consensus did NOT stall (all 10 validators' rounds advanced ~158/min,
subdags 1.3/s). BUT block height was flat 06:48:21 (36,577, round 438) -> 06:54:33 (36,578, 0 tx, round 1414):
372 s with no block, while blaster-03 (mixed until 06:57:40) and blaster-04 (until 06:50:21) were still submitting.
v03 kept sealing batches (worker batch mean 200-330 tx) yet executor outputs had no tx. Burst at 06:54 (15,766 tx: 6,978
blaster-03 own + ~8.8k foreign, likely v05's pool) right as v05 finished catching up, then nothing to the end (only
the empty epoch-closing block 36,645 at 06:57:59). Blasters 03/04/05 ended with 9,888/9,788/9,827 pending.

## 4. Backfill draft
benchmark/report/backfill/2026-10-06-certfix.json — passes make_bundle.load_backfill; a scratch make_bundle run with
it (--force, --out scratchpad/A1/out-bf) passed both leak gates (13 KPIs, 18 caveats, recovery failed_reports 0).
8 `<<RESULT>>` placeholders: summary tail sentence, upstream.branch, upstream.evidence_detail (confirm parent =
964087e02 + certifier fix only), fleet-gone time, GCS archive confirmation, tail caveat wording, harness-dirty
caveat. failed_reports filled 0 (series absent for v05; justified in _comment). compare_to r20261006-0053.
fleet.load.machine_type n2-standard-2; methodology covers blast index 2 and the index 0/1 e2 stockout aborts.
consensus is null in the scratch run only because node logs were skipped; at publish the logs supply vote_timeout.

## 5. Data gaps / oddities
- Tail inclusion gap (see §3): NOT just a false positive. Consensus was fine, but 372 s with no block while gens
  03/04 were mid-mixed; ~29.5k accepted tx never landed (03/04/05). Needs v03/v04 node logs.
- v05 executed nothing for ~2.5 min after restart (block 27,969 06:42:31-06:44:31, psi_io ~0), then executed at
  ~ the loaded chain's block rate: catch-up only finished because the load ended.
- Commit cadence slower than 0053 (0.42 vs 0.59 subdags/s; 0.90 vs 1.21 rounds/s) -> commit latency p95 up ~1 s.
- p99 time-to-land 301-635 s on every generator; ~23.6k "pinned node lost the head-of-line tx" resends (0053 ~23.7k):
  the T1 dropped-accepted-tx problem is unchanged by the certfix.
- blaster-05 errors.conn=0 despite the 5-min outage (0053: 2,158): failures surfaced as nonce-resync/scanner WARNs.
- nodes[].submitted-accepted exceeds the sum of error classes on every blaster (e.g. 01: 32,809 vs known 17,347).
- 06:35-06:36 throughput dip before the kill, spread over blasters 01/04/05/08/10.
- Index-2 create-bench-blaster logs are not in results/ (index 0/1 ones are archived); the manifest's blasters[]
  has no machine_type. n2-standard-2 evidenced by the index-2 funder create line and the operator.
- Harness tree dirty at deploy (3a31603 + uncommitted).
- Node logs not read (teardown writing them) -> provenance "inferred" in the scratch bundles.
