# Bench 5 time-to-land baseline (unit I-3, from bench 4 r20261105-0803)

Written 2026-11-06 from data only. Paths: `L/` = benchmark/private/bench5-prep/LAND/, `B4/` =
benchmark/private/bench4-r20261105-0803/, `R/` = benchmark/results/r20261105-0803/. Generator code is
tn-transaction-generator main @ 4434bac, node code the bench-5 integration head (same measurement sites as the bench-4
build). The Prometheus numbers come from a private replay of `R/logs/bench-obs-prometheus-20261105T161318Z.tar.gz`
(scrape 15 s). For the batch-pipeline co-limit, I-2p's `benchmark/private/bench5-prep/F2/batch-pipeline.json` is the reference.

## 1. What the generator measures

- `submit_ms` is stamped when the ledger entry is written, after signing and before `eth_sendRawTransaction`
  (`src/blast/sender.rs:671-683`). Identical-bytes resends keep the first stamp. A re-sign (nonce resync, fee refresh)
  is a new hash with a new stamp.
- Latency samples are own landings of a measured type whose phase *at submission* was `mixed` (`stats.rs:332-334`).
  Preamble, warm-up and cooldown submissions never contribute; cooldown landings of mixed-phase submissions do.
- `ts_ms = block_ts * 1000 - submit_ms`, clamped at 0 (`stats.rs:337-339`). The block timestamp is
  `floor(commit_timestamp_ms / 1000)`, and `commit_timestamp_ms` is the leader header's `created_at_ms`, raised to 1 ms
  above the previous commit (`types/src/primary/output.rs:597-640`). So `ts` measures submit to the creation of the
  leader header that will commit the transaction, read 0-999 ms low. It is not the commit: that comes 0.56-0.62 s later
  at idle and about 1.1-1.2 s later under load (section 4). The design's "corrected inclusion = commit_timestamp_ms -
  submit_ms" is the same instant without the floor. No millisecond timestamp is in the EVM header
  (`tn-reth/src/payload.rs:30-50`), so the correction needs the node log (L3) joined on `nonce`.
- `seen_ms` is stamped when `eth_getBlockByNumber` and `eth_getBlockReceipts` both return (`scanner.rs:505-523`). The
  head poll is 250 ms, with up to 4 block fetches in flight. The scanner reads only the generator's own node, and a
  block is on RPC only once that node has executed and persisted the whole output. Generators 07 and 08 show what
  that means: their nodes lagged, so their `seen` p50 is 28.8 and 26.7 s while their `ts` p50 is 2.1 s
  (`L/latency-by-type.json`).
- `nodes[].send_latency_ms` is the wall time of every `eth_sendRawTransaction` call, resends and preamble included
  (`sender.rs:798-806`). That is stage S0.
- Closed loop. Each sender works sequentially and waits while `next_nonce - confirmed >= window`, where `confirmed` is
  the landed nonce the scanner maintains (`sender.rs:434-470`, 20 ms poll). That gives 600 x 16 = 9,600 transactions
  in flight per generator (96,000 for the fleet), counted from submit to scanner-seen. Little's law holds:
  own tx/s x mean `seen` = 0.93-1.02 x 9,600 for the seven healthy generators (05: 0.72, 07: 0.43, 08: 0.18, all from
  refused sends; `L/latency-by-type.json littles_law`).
- What is recorded: `series.per_second` covers the mixed window only (own/chain tx, gas, distinct (epoch, round) per
  block-timestamp second), with no latency and no submissions per second. `preamble` holds counts only. `blocks.rows`
  covers every scanned block (number, timestamp, epoch, round, closes_epoch, gas, tx_count, own_*, base fee). The
  per-block `seen_ms` is internal, and there are no batch or consensus ids and no per-block submit times.

Bench 4 can therefore give the saturated `ts` and `seen` distributions per generator and per type, S0 under load, and
Little's law. It cannot give a per-stage split, a per-transaction commit time, `seen` for any phase other than mixed,
or a floor from the generator alone. The floor comes from joining the preamble's first blocks with the node logs
(sections 2 and 4).

## 2. Generator numbers (`L/latency-by-type.json`, `L/preamble.json`, `L/ramp.json`, `L/cooldown-drain.json`)

- Pooled (aggregate.py method, which reproduces A1 exactly): `ts` p50 3,303 / p95 12,837 / mean 6,430 ms; `seen` p50
  12,918 / p95 29,778 / mean 16,993 ms (10,977,032 samples). Excluding 07 and 08: `ts` 3,357 / 12,950 ms, `seen`
  12,778 / 28,277 ms.
- Shares: `ts` < 1 s 9.4 %, < 2 s 27.9 %, < 4 s 61.8 %, < 250 ms 1.3 % (this bucket includes clamped negatives).
  `seen` < 8 s 1.3 %, < 16 s 80.5 %. Nothing was seen under 4 s.
- Per type the latency is flat: all 12 mix types have `ts` p50 3.29-3.38 s and `seen` p50 12.90-12.97 s
  (`faucet_drip`: p50 2.78 s but mean 9.6 s). The queues set the latency, not the transaction type.
- Per generator `ts` p50 ranges from 2.64 s (Ashburn) to 4.12 s (Netherlands); London 3.58, Mumbai 4.06, Seoul p95
  18.6 s. Healthy `seen` p50 is 12.2-15.5 s.
- S0 under load, healthy nodes: p50 5.7-9.3 ms, p95 19-30 ms, max 98-160 ms.
- Preamble. Each generator submitted 6,600 transactions in 1.0-1.7 s on an idle chain. The first own block gives the
  transaction's submit-to-leader-creation time (true `ts`) as an interval: LA [0.20, 1.23), Sydney [0.43, 1.47), Tokyo
  [0.43, 1.44), Ashburn [0.36, 1.40), Singapore [0.35, 1.39), Hong Kong [0.29, 1.34), Seoul [0.29, 1.33), Mumbai
  [0.53, 1.57), London [0.90, 1.94), Netherlands [1.17, 2.21) s. Leader rounds 2380-2386 were 2 rounds (about 0.7 s)
  apart. "Every step landed" (seen) came 9.2-14.7 s after submission started. The 66,000-transaction burst bounds
  that number, so it is not a floor.
- Ramp. The warm-up sends native transfers only. 96,000 transactions were in flight from 09:08:46. The chain ran
  10-15 k tx/s of native transfers, a Little's-law W of 6-10 s within 10 s of the warm-up start. When the mixed phase
  started (09:10:40-46) the rate fell to 4.5-6 k and W rose to 13-21 s. The queue filled in the warm-up's first
  seconds: the first 60 s of mixed is not a fill period.
- Cooldown, by block timestamp. 41,341 own transactions (7 landing generators, about 67 k nominal in flight) still had
  to reach a leader after the cooldown started. They did so in three commits, 09:50:40, :47 and :53 (a commit every
  6-7 s at the end). The last seen landings were 16-17 s after the cooldown started.

## 3. Prometheus stages, idle against loaded (`L/snapshot.json`, `L/pool-queued.json`)

Windows: idle 08:49:09-09:00:30 (681 s), warm-up 09:08:40-09:10:40, load_all10 09:10:40-09:20:13 (573 s). Means are
exact (sum/count). p50/p95 are interpolated in 5 ms ... 30 s buckets, so they only show the shape of the
distribution.

| series (per node, mean) | idle | warm-up | load_all10 |
|---|---|---|---|
| seal duration = quorum wait (S2) | no batches | 0.18-0.38 s | 0.14-0.29 s (London/NL 0.29) |
| certificate_form (S5) | 0.130-0.192 s near, 0.223 Mumbai, 0.263-0.272 London/NL | 0.14-0.39 s | 0.19-0.71 s (p95 to 2.3 s) |
| commit_latency (leader created -> sequenced, every node) | 0.597-0.671 s | 0.76-0.89 s | 1.20-1.22 s healthy, p50 0.92 (v04 2.5, v07 8.3, v08 7.8) |
| engine queue_wait (S10) | 0.1 ms | 2.5-4.3 s | 5.0-8.9 s (p95 10-27 s) |
| engine task (S11+S12) / persist | ~0 | 0.95 / 0.13-0.16 s | 1.69-1.84 / 0.44-0.63 s |
| proposer pending digests, avg/max | 0 | 0-0.8 / 3 | 0.5-1.7 / 17 |
| batch-builder pending (its own gauge) | 0 | 62-1,110 | 53-668 |
| reth pool pending / queued, avg | 0 / 0 | - | 61-751 / 240-3,365 |
| headers/s, subdags/s | 2.89, 1.446 | 2.1, 1.0 | 1.22, 0.57 |
| vote stages exec_wait / lock (7 healthy) | < 1 ms | 96 / 71 ms | 208 / 426 ms |

At idle: the round is 346 ms (the 350 ms `min_header_delay`), every leader commits, S5 is one 6th-vote round trip, and
`commit_latency` is the pure leader-to-commit time (there is no execution wait at idle). The engine queue went from 0
to 3-4 at 09:08:45 (the preamble burst), was at 3-7 on every node by 09:09:00-09:09:15, and stayed non-empty after
that.

New finding: the reth pool's queued subpool. Under load most of each node's pool sits in `queued` (nonce gaps), not
`pending`. Over the mixed window, pool residence ((pending + queued) / own tx/s) per generator, against that
generator's `ts` mean:

| v04 | v01 | v02 | v03 | v09 | v10 | v06 |
|---|---|---|---|---|---|---|
| 1.01 s / 3.57 s | 1.44 / 3.61 | 2.22 / 5.37 | 3.77 / 7.51 | 4.19 / 9.65 | 4.69 / 10.20 | 5.36 / 11.41 |

The two series have the same rank order across the 7 healthy non-chaos generators. The mechanism, from the code:
the RPC validates a new transaction against the canonical (executed) nonce, which lags. reth sets `state_nonce` from
it and `insert_tx` parks the transaction in `queued` because the sender's sealed transactions were already pruned by
the builder (reth `pool/txpool.rs` `add_transaction`/`insert_tx`; `batch-builder/src/lib.rs:505-531`). The engine's
canonical updates (`tn-reth/src/txn_pool.rs:855-905`) regress the nonce again. A parked transaction is promoted only
when its sender is in the next sealed batch or when its predecessor *executes*. At saturation, then, S1 is 1-5 s and
tied to the engine lag, and part of what `ts` measures is execution backpressure seen through the pool.

## 4. What the existing `consensus::metrics` lines give (v01, `L/existing-lines-v01.json`)

Two early-exit `zcat` passes over `R/logs/bench-validator-01-unit-stdout.log.gz`. Windows: idle 08:55, the preamble
09:08:28-50, and load 09:17 (09:15 is the catch-up minute after the epoch boundary, at 2.1 rounds/s, so it was not used).

| stage (v01) | idle 08:55 | load 09:17 |
|---|---|---|
| round interval | 352 ms p50 | 668 p50 / 787 mean (p95 1.46 s) |
| S5 `header proposed` -> `quorum reached` (epoch, round) | 149 ms (148-151) | 228 / 276 ms |
| S3+S4 `batch sealed` -> `header proposed` (FIFO, no digest) | 184 / 206 ms (preamble) | 363 / 464 ms (p95 1.24 s) |
| own header -> committing leader's header (proxy: own header at the leader round) | 486 ms mean (odd 379, even 593) | 1,178 mean (odd 840, even 1,507) |
| leader created -> `subdag committed` | 558 ms proxy, 616 ms exact when v01 led (n=12) | 1,126-1,195 (own-leader 841-1,064) |
| `subdag committed` -> `consensus output ready` | 2 ms | 3 ms |
| queue_wait / task / execute / persist (engine fields) | 0 / 0 | 10.0 s / 1.57 / 1.09 / 0.48 s p50 |
| batch size, seal interval | - | 333 tx p50 (gas-limit full, max 398), 170 ms p50 |

The first preamble batch traced end to end on an idle chain: generator 01 started submitting at 09:08:30.767.
Batch sealed at 30.992 (183 tx; it missed header 2378 by 3 ms), header 2379 at 31.341, quorum at 31.491, leader 2380's
header at about 31.69 (block ts 31), commit at 32.269, output ready at 32.270, block 191 executed at 32.307, output
persisted at 32.379 (execute 85 ms, persist 18 ms). That makes true `ts` 0.92 s, read `ts` 0.23 s, visible at
1.61 s and seen about 1.74 s.

Joins possible today: own header -> quorum on (epoch, round); own `certificate committed` (origin, round);
`subdag committed` -> `consensus output ready` on leader_round; `consensus_number` through the engine lines; block
number. Joins impossible today: batch -> header (no digest on `batch sealed` or `header proposed`), batch -> block,
pool age, report time, the age of foreign certificates, fetch/pack persist, engine queue entry, the commit instant
after the execution wait (`subdag committed` and `certificate committed` are logged inside Bullshark before
`state.rs:621-622`), cancelled and never-committed own headers (debug only), and transaction -> block on the generator
side. These gaps justify L1-L5 and T1.

## 5. Floor and decomposition (`L/floor-decomposition.json`)

| stage | idle near (v01) | idle far (London/NL) | saturated v01 (means) | kind / source |
|---|---:|---:|---:|---|
| S0 RPC accept | 0.006 | 0.008 | 0.006 | measured under load, §2 |
| S1 pool wait | 0.10 | 0.10 | 1.44 | idle predicted (tick 250 ms); saturated Little, §3 |
| S2 seal -> 2f+1 acks | 0.17 | 0.37 | 0.165 | measured, §3 |
| S3 report | 0.005 | 0.005 | 0.005 | unmeasured |
| S4 digest wait | 0.18 | 0.18 | 0.46 | measured (FIFO), §4 |
| S5 certification | 0.15 | 0.27 | 0.36 | measured, §3-4 |
| S6a own cert -> committing leader created | 0.34 | 1.08 | 0.90 | v01 measured; far inferred: 70.6/70.2 % of their idle certificates never committed (B4/A2/certification.md) |
| S6b leader created -> commit (+S7 under load) | 0.59 | 0.62 | 1.20 | measured, §3-4 |
| S8+S9 fetch + pack persist | 0.002 | 0.002 | 0.003 | measured, §4 |
| S10 engine queue | 0.02 | 0.02 | 6.22 | measured, §3 |
| S11 execute (whole output) | 0.15 | 0.15 | 1.27 | measured, §4 |
| S12 persist + announce | 0.03 | 0.03 | 0.46 | measured, §3-4 |
| S13 scanner visibility | 0.14 | 0.14 | 0.15 | inferred (250 ms poll) |
| **true `ts` (S0-S6a) / read** | **0.95 / 0.45** | **2.01 / 1.51** | **3.34 / 2.84** | |
| **commit (+S6b)** | **1.54** | **2.63** | **4.54** | |
| **seen (sum)** | **1.88** | **2.98** | **12.64** | |

Checks. The near model (1.88 s) sits on the v01 preamble trace (seen about 1.74 s). For saturated generator 01 the
model gives 12.6 s, and 13.4 s with the measured `ts` in place of S0-S6a. The measured `seen` mean is 13.72 s.

- Sub-second bias: the published `ts` p50/p95/mean of 3.30 / 12.84 / 6.43 s become 3.80 / 13.34 / 6.93 s once the
  whole-second floor is deconvolved (histogram convolved with U[0,1) s; resolution ±0.1 s). At the floor the bias
  dominates: true 0.9-1.0 s reads 0.2-0.5 s and falls in the < 500 ms buckets.
- Time to commit, as an estimate: corrected `ts` p50 plus the loaded leader-to-commit p50 = 3.80 + 0.92 = about 4.7 s.
- Best estimate of the idle protocol floor: `seen` about 1.9 s near and about 3.0 s far, fleet p50 about 2.0 s and
  p95 about 3 s. True `ts` is about 0.95 s near (reads about 0.45 s) and about 2.0 s far. The round-denominated stages
  S4 + S6a + S6b are 1.11 of the near 1.88 s (59 %).
- Saturated `seen` p50 12.9 s, from generator 01's means: engine queue 6.2 s (45 %), pre-leader `ts` 4.1 s (30 %, of
  which pool residence 1.4 s here and up to 5.4 s on other nodes), leader -> sequenced 1.2 s (9 %), execute + persist
  1.7 s (13 %), scanner 0.15 s.

## 6. The light-load arm

In flight = 10 x S x 16. At a `seen` floor of 1.8-2.4 s (§5):

| senders/gen | in flight | tx/s | % of 4.6 k | samples in 360 s (per gen) | engine busy at 140-215 us/tx |
|---|---:|---:|---:|---:|---:|
| 8 | 1,280 | 530-710 | 12-15 % | 190-256 k (19-26 k) | 0.07-0.15 |
| 16 | 2,560 | 1,070-1,420 | 23-31 % | 384-512 k (38-51 k) | 0.15-0.31 |

- Saturation needs about 9,200 in flight (about 58 senders at window 16; 32 senders would be 46-62 %). At 16 senders an output carries about
  900 transactions; the preamble outputs of 0.7-1.1 k took 85-158 ms to execute and 18-22 ms to persist (§4), so the
  queue stays at 0-1 and S10 is about 20-50 ms. The ramp data shows no sign that 16 senders would fill the queue: it
  filled only under the 66 k preamble burst and the 96 k warm-up.
- 360 s is enough. The rarest types still have more than 400 samples per generator, and p95 is stable to within one
  bucket. The risk is not sample count but the 1,200 s epoch: each light index has about a 40 % chance of containing a
  boundary. The floor windows should drop boundary ± 30 s (from `epochs[].closed_at_unix`), or start each light index
  right after a boundary.
- A third light point adds little. 8 and 16 senders both sit in the queue-free regime, so they measure the floor
  twice. The 600 x 4 saturated point is worth a fourth index, run chaos-off before the chaos load. It is the only
  direct test of "saturated latency = in flight / throughput": 24,000 in flight should give a `seen` mean of
  5.2-6.9 s at the same throughput. Throughput may fall with smaller outputs because the per-output persist has a
  fixed cost (I-2p's F2 is the reference). It also shows the queued-pool effect at a quarter of the depth. It needs a
  per-index window in H1.
- Recommended: index 0 `8x16`, index 1 `16x16` (warm-up 60 s, mixed 360 s, cooldown 60 s, chaos off), index 2
  `600x4` (same durations, chaos off), index 3 the bench-4 profile with chaos. `BENCH_LIGHT_LOAD_AFTER` should stay
  off unless the committee is whole after the chaos load. Otherwise the post-load floor mixes in F1/F3 demotions.
  Optional: `128x1` (the same in flight as 8x16 at window 1) separates the per-sender nonce chain from the protocol
  floor (§3).
- Window 16 at light load: a sender's window travels as a convoy (16 serial sends of 6 ms each). When a convoy is
  split across two outputs, the next convoy parks in `queued` until the second output executes (§3), which adds up to
  one output interval. T1's per-block own_submit quantiles and the L1 `queued_before` field below make this visible.

## 7. Levers, re-ranked with this data

Below saturation (near floor 1.9 s; far 3.0 s):

| lever | stage moved | size today (idle) | predicted gain idle / saturated | bench-5 field that proves it |
|---|---|---|---|---|
| 1. round time: `min_header_delay` 350 -> 250, or threshold 5 -> 1 / no min delay while digests are pending (one lever: at idle and under load headers carry 0-2 digests, so the threshold of 5 never fires, §4) | S4, S6a, S6b (about 3.2 rounds) | 1.11 s of 1.88 | -0.3 to -0.5 s / ~0 (loaded rounds are vote-bound: exec_wait 208 ms, lock 426 ms) | round interval, `oldest_digest_wait_ms`, `certificate committed age_ms`, light-window seen p50. Arm in bench 6; may hurt the far pair |
| 2. fast direct commit (#532) | S6b | 0.56-0.62 s | -0.3 to -0.4 s / -0.6 s of 12.9 | `subdag committed leader_created_at_ms` - `commit_timestamp_ms` |
| 3. far-validator inclusion (min delay 400-450 control, or re-sending never-committed digests sooner) | S6a for London/NL | 70 % of their idle certificates never committed (+~1 s) | far floor -0.7 s / small | per-generator light floor; a new line on the digests-resend path (below) |
| 4. multi-anchor (#552) | S6a (even-round penalty) | even 593 vs odd 379 ms | -0.1 to -0.2 s / ~0 | own header -> leader header by parity |
| 5. L6 wake-on-arrival / `max_batch_delay` 250 -> 100 (the same stage: pick one) | S1 tick part | <= 0.125 s mean (first preamble batch <= 0.07 s) | -0.05 to -0.1 s / 0 | L1 `wake=` and `pool_age_p50_ms` in light windows |
| 6. L7 re-queue on cancel | S4/S5 tail | ~0 at idle (99.6-100 % certified) | 0 / trims p95 of Seoul (31.5 % uncertified under load), Mumbai 13 %, Sydney 12.3 % | `header uncertified reason=canceled` count, the digests' next inclusion |

At saturation: throughput first (E1/E4/E5, then pipelined persist and parallel state root). At fixed in-flight,
`seen` = in flight / throughput, and the engine lag also feeds S1 through the queued pool. Second, a new bench-6
candidate: stop canonical updates from regressing a sender's pool nonce below the builder's mined nonce (or validate
RPC transactions against it). That removes 1-5 s of S1, but it changes batch contents, so bench 5 only measures it. In
a closed loop, removing it moves the wait into the engine queue rather than cutting `seen`. Rejected again: k batches
in flight per worker. Under load the batches are gas-limit full at a 170 ms seal interval, about 1.9 k tx/s of
capacity per worker against 650 offered. Only bursts (the preamble) hit the one-batch limit.

Claims in the design that the data contradicts:
1. "S1 125 -> 25-50 ms (L6)": at saturation S1 is 1.0-5.4 s, mostly nonce-gap `queued`. L6 reaches only the tick
   part, and only below saturation.
2. "`ts` = consensus inclusion" and "corrected inclusion = `commit_timestamp_ms` - submit": both are submit -> leader
   header creation, 0.56-0.62 s (idle) and 0.9-1.2 s (loaded) before the commit. Under saturation `ts` also contains
   execution-coupled pool wait.
3. "Bench 4 has NO usable floor sample": the preamble's first blocks are one. The v01 trace gives 1.61 s to visible,
   and all ten generators have bounded first-landing intervals (§2).
4. "`commit_latency_seconds` (leader only)": it is recorded on every node for every sub-DAG, from the leader's
   `created_at` to after the execution wait. At idle it equals S6b.
5. S6 as `certificate committed age_ms` <-> `subdag committed`: the two lines are the same instant, before the
   execution wait. S7 needs a timestamp after `state.rs:621-622` (or wherever F1 moves the wait).
6. The predicted floor (seen 2.2 s; `ts` 1.2 s true, 0.7 s read): near nodes are lower (1.9 / 0.95 / 0.45 s), far
   nodes higher (3.0 / 2.0 / 1.5 s). The spread between generators will be large, so the floor has to be reported per
   generator.

Fields to add, from this data: L1 `batch built` += `queued_before` (`pool_size().queued`); L3 += one info line on the
proposer's digests-resend path (`proposer.rs:711-768`), `digests resent count= from_round= round=`, and a post-wait
timestamp or `exec_wait_ms` for S7; L5 `output queued` at info (one line per output) or kept by the bench-5 engine
filter; T3 `PROM_SERIES` += `reth_transaction_pool_{pending,queued}_pool_transactions`,
`reth_transaction_pool_all_transactions_by_hash`; the stage tool and KPIs exclude epoch boundary ± 30 s from the
light windows and report the floor per generator.
