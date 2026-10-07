# Latency adjustments: the fastest block cadence a ten-region fleet supports

Status: reviewed 2026-10-06; stage 1 ran as run r20261006-2058 the same night and **§9 holds the measured
results, which overturn the §1 cadence prediction** (idle round 530-550 ms, London and the Netherlands do not
certify in any arm). Sections 1-8 are kept as written for the record. Originally written 2026-10-06 from the measured inter-zone
latency matrix (`benchmark/latency/2026-10-06/`), the node code at telcoin-network `ba43a1f0e`
(branch `devnet-bench-10-5-2026`), the logs of runs r20261006-0053 and r20261006-0458, and a small
timing model (`benchmark/tools/cadence-model.py`) calibrated on those logs.

## 1. Summary

**What paces a round.** With no load, a validator proposes the next round as soon as it holds a
quorum (7 of 10) of the previous round's certificates and its `min_header_delay` timer has fired.
In run 0458 the timer (250 ms) had already fired by the time the quorum arrived: near validators
needed 282-306 ms to certify a header, and the round period was 349 ms. **The idle round is set by
certificate formation, not by `min_header_delay`.** Lowering the minimum delay below ~300 ms
changes nothing; raising it above ~300 ms slows the chain one-for-one.

**Why Sydney certified 0 % of its headers.** A validator's header is certified only if its votes
arrive before the fleet moves to the next round, which happens one round period (349 ms) after the
header went out. Sydney needs votes from six remote validators; in the old layout the sixth-nearest
was London or the Netherlands at 314 ms RTT, so its certificate took longer than the round. It was
canceled every time. No Sydney-only setting can fix that: the window is set by the seven fastest
certificates, and those are not Sydney's.

**What the ten-region layout does.** It spreads the fleet so that no validator has a cluster of
near voters and none is stranded: the slowest validator's sixth-nearest peer drops from 314 ms
(Sydney, old) to 231 ms (Sydney, new), while the median rises from 138 to 158 ms. The model predicts
every validator certifies and is referenced in every round, with an idle round of about **400 ms
(2.5 rounds/s, a leader commit every ~0.8 s)** at any `min_header_delay` up to 300 ms. Sydney's
margin is thin (certifies at ~366 ms into a 403 ms round), so the sweep must measure it.

**Recommended fleet configuration (every node the same):**

| key | today | recommended | why |
|---|---|---|---|
| `min_header_delay` | 250ms | **250ms** | any value ≤ 300 ms gives the same cadence; 250 keeps the leader shortcut (zero delay for the next leader) from canceling the leader's own previous header |
| `max_header_delay` | 500ms | **1000ms** (arm) | under load the round is ~900 ms, so a 500 ms maximum fires every round and re-proposes the same header (~70 re-proposals/min/node in 0458); 1000 ms removes that churn and still bounds the wait for a dead leader (the next leader waits half of it) |
| `vote_timeout` | 5s (default) | 5s | must stay ≥ max_header_delay + 250 ms and < 10 s |
| `header_num_of_batches_threshold` | 5 | 5 | unchanged; under load it already skips the minimum delay |
| `max_batch_delay` | 250ms | 250ms | unchanged |

The stage-1 sweep (section 6) confirms the prediction with five arms, then stage 2 runs the chosen
arm for 40 minutes with the chaos kill.

## 2. Observed (runs 0053 and 0458, five-zone layout, 250 ms / 500 ms)

Idle window of run 0458 (05:30-05:59 UTC; `benchmark/tools/propose-latency.py`):

| validator (zone) | proposed | certified | C = propose → own quorum p50/p95 | round period p50/p95 |
|---|---:|---:|---|---|
| 01, 02 (LA) | 3205 | 3205 (100 %) | 287 / 289, 288 / 291 ms | 349 / 395 ms |
| 09, 10 (London) | 3205 | 3205 (100 %) | 285 / 290, 282 / 285 ms | 348 / 395 ms |
| 07, 08 (Netherlands) | 3205 | 3204 (100 %) | 304 / 308, 306 / 309 ms | 348 / 395 ms |
| 05, 06 (Montréal) | 3205 | 3205 (100 %) | 182 / 184, 180 / 183 ms | 357 / 389 ms |
| 03, 04 (Sydney) | 3205 | **0 (0 %)** | — (1823 / 1765 canceled) | 349 / 395 ms |

The certification times are within 3 ms of their medians: a deterministic path, not jitter.

Under load (06:10-06:35, mixed phase): round period p50 900 ms (p95 1797); LA certified in
339 / 1038 ms (p50 / p95) at 95.4 %, the Netherlands in 579 / 1342 ms at 90.4 %, Sydney in
703 / 1495 ms at 66.8 %. Over the whole mixed phase (tasks/stall/A2-logs.md, tools/cert-rate.py):
Sydney validators certified 60.4 % and 67.8 % of their headers, were the leader of 0.1 % and 0.8 % of
committed subdags (fair share 10 %), and about a third of the certificates they did form were never
committed. When only the Sydney blasters were still sending (06:48:21-06:54:33) no batch entered a
certificate for 372 s. Execution ran at 13.7 blocks/s (one block per batch), commit latency p50
1.75 s and p95 4.2 s. Rounds slowed from 2.0/s to 0.8/s as execution saturated at 14-16 blocks/s.

## 3. Mechanics (telcoin-network `ba43a1f0e`)

- **All timing parameters are per node.** `min_header_delay`, `max_header_delay`, `max_batch_delay`,
  `vote_timeout`, `header_num_of_batches_threshold`, `max_header_num_of_batches` are read from
  `<datadir>/parameters.yaml` at startup (`crates/config/src/node.rs:89-93`, `211-314`). Neither the
  committee nor genesis fixes them, and a voter never checks a proposer's pace. Only
  `basefee_address` must match (`node.rs:275-294`); `gc_depth` should (it is the DAG prune point).
  Startup requires min ≤ max and `vote_timeout` ≥ `max_header_delay` + 250 ms drift tolerance and
  < 10 s (`crates/config/src/consensus.rs:492-520`, `network.rs:428`).
- **When a node proposes** (`proposer.rs:1002-1011`): it has parents (a quorum of the previous
  round's certificates) and either the max timer fired, or the round is ready and (≥ 5 batch digests
  are pending or the min timer fired). The min timer is re-armed when the previous proposal finished
  building (`proposer.rs:875-891`), not when parents arrive (`:640-660`), so idle rounds run at
  max(min delay + build time, time for the 7th certificate to arrive). The node that expects to lead
  the next even round uses a zero min delay and half the max delay (`proposer.rs:451-483`).
- **A header's vote window is one round period.** The certifier drops the in-flight header when the
  proposer hands it the next one (`certifier.rs:628-638`, `:232-235`, "Canceled"). A far node proposes
  round r the moment the round r-1 quorum reaches it and abandons it when the round r quorum does,
  so its window is the fleet's round period T whatever its own settings. **Lowering only the far
  node's `min_header_delay` cannot widen the window. A far-node `max_header_delay` below T makes it
  re-send and re-arm its timers, delaying it further** (`proposer.rs:961-965`, `:880-885`).
- **Certification time** C ≈ build + RTT to the 6th-nearest voter + voter processing + aggregation
  (`certifier.rs:319-332` requests all votes in parallel). A voter that has not yet received a
  parent answers MissingParents and the proposer re-sends with the parents attached: one extra round
  trip (`certifier.rs:155-195`, `handler.rs:644-680`). Under load a voter also waits for its own
  execution to reach the header's execution block (`handler.rs:912-915`).
- **Referenced or orphaned.** A certificate is used only if it reaches other nodes before they
  propose the next round; parents must be exactly the previous round (`handler.rs:980`,
  `proposer.rs:630-639`). An orphaned certificate's batches are re-queued only when one of the node's
  own headers is committed (`proposer.rs:684-731`), which never happens to a node that certifies
  nothing: hence the 372 s inclusion gap.
- **Blocks.** Leaders are elected on even rounds (`consensus/bullshark.rs:137-145`): one commit per
  two rounds; execution makes one block per batch and skips empty outputs, so an idle chain has a
  commit cadence but no blocks, and a loaded chain is bounded by execution (14-16 blocks/s observed).
- **Transport.** Both primary and worker networks are QUIC over UDP only
  (`crates/network-libp2p/src/consensus.rs:691-707`, `Cargo.toml:12-19`; addresses are
  `/udp/<port>/quic-v1`, `crates/types/src/primary/info.rs:70`). Certificates are flood-published on
  gossipsub (`consensus.rs:257`, `primary/src/network/mod.rs:412`); votes are request-response. The
  UDP matrix is therefore the one that applies.

## 4. Measured latency matrix (2026-10-06)

Method: one `e2-small` probe VM per zone on the default VPC, internal addresses, 40 pings, 40 UDP
echoes of 1200 bytes (QUIC-sized) and 20 TCP connects per ordered pair, 18 zones. Tables:
`benchmark/latency/2026-10-06/matrix-{udp,tcp,icmp}.{md,csv}`, `tcp-vs-udp.md`, `kth-nearest-*.md`.

Findings:
- **No UDP loss on any of the 153 pairs.** UDP and TCP round trips agree within 10 % on 148 pairs;
  the 5 flagged pairs are sub-millisecond or 15-22 ms pairs where the TCP connects happened to land on
  a faster path. Nothing suggests UDP is treated worse than TCP anywhere.
- **Each direction can take a different path.** Sydney ↔ London measured 301 ms one way and 327 ms
  the other; TCP connects (new source port each) landed at 275, 301 and 327 ms. A QUIC connection
  stays on one path, so a validator pair's real RTT on long routes varies by about ±25 ms with the
  ports it happens to use.
- **The log-derived "200-449 ms one-way" figures from the stall investigation were inflated.** The
  widest measured RTT inside the final layout is 315 ms (Sydney ↔ Netherlands), i.e. ~160 ms one way;
  the log differences included queueing during the stall.

RTT to the 5th and 6th nearest peer (UDP, ms), per validator:

| old layout (two per zone) | 5th | 6th | | final layout (one per region) | 5th | 6th |
|---|---:|---:|---|---|---:|---:|
| us-west2 (LA) | 136.6 | 137.9 | | us-west2-a (LA) | 137.9 | 143.4 |
| australia-southeast1 (Sydney) | 232.8 | **314.0** | | europe-west2-b (London) | 166.4 | 200.1 |
| northamerica-northeast1 (Montréal) | 107.6 | 111.1 | | australia-southeast1-c (Sydney) | 174.2 | **231.0** |
| europe-west4 (Netherlands) | 107.6 | 148.8 | | asia-northeast1-b (Tokyo) | 117.0 | 120.7 |
| europe-west2 (London) | 111.1 | 136.6 | | northamerica-northeast1-b (Montréal) | 199.5 | 223.2 |
| | | | | europe-west4-a (Netherlands) | 163.9 | 197.2 |
| | | | | asia-southeast1-b (Singapore) | 163.9 | 163.9 |
| | | | | asia-east2-a (Hong Kong) | 143.4 | 151.4 |
| | | | | asia-northeast3-a (Seoul) | 126.8 | 127.7 |
| | | | | asia-south1 (Mumbai) | 149.1 | 152.1 |

Layout notes: Jakarta (asia-southeast2) offers no `c3-highcpu-8` in any zone, so validator-07 runs in
Singapore (`tasks/regions/evaluation.md`); Mumbai's C3 zone is `asia-south1-c`, which was not probed,
so `asia-south1-a` (same metro) stands in. Hong Kong's alternate is Taiwan (`asia-east1-a`). The
widest pairs inside the final layout: Sydney ↔ Netherlands 315, Sydney ↔ London 314, London ↔ Seoul
261 ms.

## 5. Model and calibration

`benchmark/tools/cadence-model.py` is a discrete-event model of the rules in section 3 on the UDP
matrix (one-way = RTT/2): proposal when quorum + min timer, parallel vote requests, MissingParents
as one extra round trip, cancel on the next proposal, "referenced" if any node holds the certificate
before proposing the next round, the leader's zero min delay. Three processing constants are fitted
to the 0458 idle window: build 60 ms, voter 45 ms, aggregation 30 ms (135 ms per header in total).

| 0458 idle, old layout | measured | modelled |
|---|---:|---:|
| round period p50 | 349 ms | 353 ms |
| C, LA / London / Netherlands | 287 / 285 / 304 ms | 273 / 272 / 284 ms |
| C, Montréal | 181 ms | 246 ms |
| Sydney certification | 0 % | 0 % |

The model gets the round, the peripheral nodes and Sydney's failure right, and under-predicts how
much faster the central node certifies by ~65 ms: something in the real vote path favours a node
whose voters are all within ~110 ms more than geometry alone explains (candidates: the MissingParents
round trip hitting peripheral proposers, gossip validation delaying parents at far voters). The
debug-filter run in stage 1 records each vote request and response, which settles it. Until then,
per-node predictions carry about ±40 ms.

Predictions, `max_header_delay` = max(500, 2 × min):

| layout | min delay | round p50 | rounds/s | validators certifying < 99 % | referenced < 99 % | slowest C p50 |
|---|---:|---:|---:|---|---|---|
| old | 50 - 250 | 353 | 2.84 | Sydney ×2: 0 % | — | 284 (Netherlands) |
| old | 300 | 360 | 2.78 | Sydney ×2: 0 % | — | |
| old | 400 | 460 | 2.17 | Sydney ×2: 95 % | — | 449 (Sydney) |
| old | 500 | 560 | 1.79 | Sydney 95 %, six others 98 % | — | |
| **final** | **50 - 300** | **403** | **2.48** | **none** | **none** | **366 (Sydney)** |
| final | 350 | 410 | 2.44 | none | none | 366 |
| final | 400 | 460 | 2.17 | Sydney 99.6 % | Sydney 95 % | 366 |
| final | 500 | 560 | 1.79 | London, Sydney, Montréal, Netherlands 95 % | none | 366 |

Per validator on the final layout at 250 ms: C p50 = Tokyo 256, Seoul 263, LA 278, Hong Kong 286,
Mumbai 287, Singapore 299, Netherlands 332, London 335, Montréal 358, Sydney 366 ms; round 403 ms.
The spread is narrow because every validator now has about the same mix of near and far voters, so
the 8th-10th certificates form within 35 ms of the 7th and well inside the ~40-70 ms it takes the
quorum to propagate. With the voter constant 20 ms higher the round is 423 ms and Sydney still
certifies 100 %; 20 ms lower, 383 ms and 100 %.

Three readings of the table:
1. **The lever for idle cadence is not `min_header_delay`** below ~300 ms; the floor is certificate
   formation (135 ms processing + the slowest node's 6th-nearest RTT + propagation). The sweep's
   50 ms arm tests this directly: if the round stays near 400 ms, the model is right.
2. **A large min delay costs certifications through the leader shortcut:** at 500 ms, the node that
   will lead the next even round proposes at the quorum (~400 ms) while everybody else waits to
   500 ms, and cancels its own previous header if that header has not certified yet (5 % at four
   nodes). At 400 ms Sydney's certificates start arriving after others have proposed (95 %
   referenced). So more delay is not more margin.
3. **The old layout could never have worked for Sydney** below a 400 ms minimum (460 ms round), and
   even then at 95 %. This matches the 0053 and 0458 logs exactly.

Under load the model does not apply: the 0458 round was 900 ms because voters wait for execution
(`handler.rs:912-915`) at 14-16 blocks/s. In that regime every validator has a 900 ms window and
Sydney certified 67 % with C p50 703 ms (execution waits add to its RTT). The sweep measures the
loaded regime per arm; the expectation is that it is the same across arms and that the ten-region
layout lifts Sydney's loaded rate because its 6th-nearest RTT fell by 83 ms.

## 6. Recommended arms and pass criteria (stage 1)

Fleet: the ten-region layout, image `adiri:mmap-subsecond-certfix-10-6-2026` (digest re-probed at
the gate), txgen `blast-v2-9f61303`, node log filter `info,primary::certifier=debug,primary::proposer=debug`
on every node (per-peer vote timing and parent choice in the logs), chaos off. Each arm: parameters
applied fleet-wide with `tools/params-apply.sh` (serial restarts, one node down at a time, verified
read-back, `--stage-test` on the observer first), then ~8 min idle, then a 480 s blast (60 s warm-up,
60 s cool-down). Per arm the harness records rounds/s, blocks/s, tx/s, commit latency, per-node
certification, own-leader share and not-committed share (`tools/cert-rate.py`, `block-rate.py`,
`propose-latency.py`, Prometheus).

| order | arm | min / max (ms) | tests | prediction |
|---|---|---|---|---|
| 1 | A0 baseline | 250 / 500 | the new layout as-is | round ~400 ms idle; every validator ≥ 99 % certified; Sydney C p50 ~370 |
| 2 | A1 fast (user's) | 50 / 250 | min below the floor, max below the round | round unchanged ~400 ms; max timer fires every round → a re-proposal per round per node; certification unchanged or slightly worse |
| 3 | A2 margin | 400 / 800 | whether more delay buys margin | round ~460 ms (2.2/s); Sydney certified but ~5 % of its certificates arrive too late to be referenced |
| 4 | A3 wide max | 250 / 1000 | the loaded regime without max-timer churn | idle unchanged; under load re-proposals fall from ~70/min to near zero; certification under load equal or better |
| 5 | A4 slow | 500 / 1000 | the slope and the leader shortcut | round ~560 ms (1.8/s); 4 validators lose ~5 % to the leader shortcut |

Pass criteria per arm (idle window and load window separately): every validator certifies ≥ 90 %
of its own headers idle and ≥ the baseline's rate under load; own-leader share within 10 points of
the median (fair share 10 %); not-committed share ≤ 10 %; no node's C p95 above the fleet's round
p50 (the margin proxy). **Best = the fastest round among passing arms with that margin.** On the
model that is A0 or A3 (same cadence; A3 preferred if the loaded regime shows fewer re-proposals and
no loss of certification). Expected stage-1 budget: ~45 min deploy + 5 × ~20 min + collect and
teardown ≈ 3.5 h.

Stage 2: the chosen arm fleet-wide (`BENCH_PARAMETERS_FILE` values, no per-node overrides), chaos on
(epoch-timed kill of validator-05 in Montréal), 40-minute mixed phase, same filter; report every
validator's certification idle and under load, orphan/not-committed share, inclusion gaps, blocks/s,
the KPI table against 0458 and 0053, and `cert_failures` with preserved log paths if any.

## 7. Risks and unknowns

- **Processing constants are fitted, not measured.** 135 ms per header is large for signature
  checks and writes; the debug filter run shows where it goes (vote request → response per peer,
  MissingParents count, gossip arrival of parents). If the 65 ms Montréal discrepancy is a
  MissingParents effect, peripheral nodes on the new layout may certify ~40 ms later than modelled;
  Sydney's 37 ms margin then disappears in idle and A0 would show Sydney at a partial rate. That is
  exactly what the sweep is for; A2 (400 / 800) is the fallback with a 2.2 rounds/s cadence.
- **QUIC path pinning:** ±25 ms per pair on long routes; a node's RTT to its 6th-nearest voter can
  differ from the matrix by that much in either direction for the life of a connection.
- **Leader reputation.** The model uses round-robin leaders. Bullshark's reputation schedule can
  swap slow leaders out; a node that is never the leader never has own headers committed as leader
  and loses the batch re-queue trigger (section 3).
- **The loaded regime** is execution-bound (14-16 blocks/s); parameters do not move it. Cadence
  under load is a throughput question (batches per round), not a timing one.
- **Layout deviations from the request:** Singapore instead of Jakarta (no C3 highcpu there);
  Mumbai in zone c (not probed, same metro). Probe VMs were `e2-small`, the nodes are `c3-highcpu-8`;
  the network fabric is the same, the hosts are not.
- **Calibration is from one run** (0458, certfix image). The sweep uses the same image.

## 8. Appendix: data, tools, reproduction

- Matrix tables: `benchmark/latency/2026-10-06/` (committed); raw per-zone JSON:
  `benchmark/results/latency/20261006T175053Z/` (local only).
- Region evaluation: `tasks/regions/evaluation.md`. Run 0458 artefacts: `benchmark/results/r20261006-0458/`
  (local only; the GCS archive was verified against it and deleted, `tasks/archive/verify.md`).
- Tools (`benchmark/tools/`, documented in `README.md` and `ANALYSIS.md`): `latency-probe.sh` +
  `latency-matrix.py` (any project, VPC, zone list), `cadence-model.py` (any matrix and layout),
  `propose-latency.py` (calibration from any node's logfmt log), `cert-rate.py`, `block-rate.py`,
  `params-apply.sh` (live parameter arms on any fleet via a nodes file).
- To repeat on another network: probe its zones, run `cadence-model.py` with its layout, pull a
  quiet hour of logs and run `propose-latency.py` to re-fit the three constants, then apply arms
  with `params-apply.sh` and read them back with `cert-rate.py --windows`.

## 9. Stage 1 results (run r20261006-2058, 2026-10-06 20:59 UTC to 2026-10-07 01:40 UTC)

Fleet and image as §6 specified: ten `c3-highcpu-8` validators, one per region, plus the observer in
LA; image `adiri:mmap-subsecond-certfix-10-6-2026` (digest `sha256:caeb6be2…`, node sha `ba43a1f0e`);
txgen `blast-v2-9f61303`; node log filter `info,primary::certifier=debug,primary::proposer=debug`;
chaos off. The five arms ran in order, each applied fleet-wide with `tools/params-apply.sh` (11 serial
restarts, every node back in consensus in 10-20 s), then ~8 min idle and a 480 s blast. Teardown passed
the local gate; `benchmark/results/r20261006-2058/` is the only copy (748 files, 1.58 GB). Full tables:
`benchmark/results/r20261006-2058/analysis/stage1-summary.md` and `analysis/per-arm/`.

### 9.1 Measured, per arm

| arm | min / max (ms) | idle round p50 / p95 (ms) | loaded round p50 (ms) | loaded rounds/s | blocks/s | tx/s | commit p50 / p95 (s) | re-proposals per min per node, idle / load | lowest own-header certification idle (node) | §6 |
|---|---|---|---|---|---|---|---|---|---|---|
| A0 | 250 / 500 | 550 / 756 | 670 | 1.36 | 14.95 | 4806 | 1.65 / 2.42 | 92 / 79 | 21.0 % (Netherlands) | fail |
| A1 | 50 / 250 | 538 / 570 | 755 | 1.22 | 14.36 | 4238 | 1.68 / 2.42 | 194 / 177 | 0.7 % (Netherlands) | fail |
| A2 | 400 / 800 | 527 / 555 | 676 | 1.33 | 15.80 | 4839 | 1.74 / 2.42 | 5.7 / 23 | 4.5 % (Netherlands) | fail |
| A3 | 250 / 1000 | 530 / 558 | 630 | 1.41 | 15.84 | 5005 | 1.72 / 2.42 | 4.9 / 9.4 | 6.7 % (Netherlands) | fail |
| A4 | 500 / 1000 | 527 / 555 | 655 | 1.24 | 14.45 | 4271 | 1.75 / 2.42 | 5.1 / 13.8 | 6.4 % (Netherlands) | fail |

Time from a node's own proposal to its own quorum (C, p50, ms), the same in every arm: Seoul 264,
Tokyo 272, LA 297, Hong Kong 297, Singapore 344, Montréal 406, Sydney 427, Mumbai 449-467,
**London 556-564, Netherlands 580-585**. Eight validators certify 91.5-100 % of their own headers idle
(Sydney 92.5 % in A0, 99.7-99.9 % in the others). London certifies 7-50 % and the Netherlands 0.7-21 %
in every arm, hold 0-2 % of leader slots against a fair 10 %, and 75-100 % of the certificates they do
form are never committed. Under load London and the Netherlands reach 59-85 %, Mumbai 74-90 %.

### 9.2 What the measurements say

- **The central claim of §1 holds: `min_header_delay` does not pace the idle round.** 50 ms gave 538 ms,
  250 ms gave 530-550 ms, 400 and 500 ms gave 527 ms. The min timer never bound; the round is set by the
  arrival of the seventh certificate, about 525 ms after a proposal.
- **The predicted cadence does not hold.** The model said ~400 ms with every validator certifying; the
  fleet runs at 530-550 ms because the seventh-fastest certificate is Mumbai's (~455 ms) once London and
  the Netherlands drop out of the quorum pool, and because every node's C is 20-170 ms slower than
  modelled.
- **Why London and the Netherlands fail.** Their sixth vote arrives 555-580 ms after they propose; the
  next round's seven parents arrive at ~530 ms; so they propose the next round and cancel their own
  header (`new proposal received - aborting proposal`, then `Canceled`). The cut-off is sharp: own headers
  alive under 540 ms certified 0 %, over 575 ms 90-100 %. The cause is in the vote path itself: the
  vote round trip on every link is fixed, symmetric and about **twice the measured UDP RTT**. The Asian
  voters answer London and the Netherlands in 472-724 ms (Tokyo 472, Seoul 523, Sydney 554, Hong Kong
  559, Singapore 594, Mumbai 724) and answer LA in 204-450 ms. Nothing on the proposer side explains the
  doubling (no missing-parent re-requests, no vote errors except `Canceled`); the vote-request handler was
  not in the debug filter. Two causes, both outside the timer parameters, were then found in the node
  source and confirmed against the run's own per-link vote timings:
  1. **Every vote request pays one extra round trip for protocol negotiation.** Each request opens a new
     libp2p substream and negotiates its protocol in strict multistream-select `V1` mode: the requester
     waits for the voter's protocol confirmation before sending the request bytes (the swarm builder in
     `network-libp2p/src/consensus.rs:691-716` sets no substream upgrade override; libp2p-swarm 0.48
     defaults to `V1`; request-response 0.30 opens one substream per request). Certificates travel on
     gossipsub's long-lived substreams and arrive in half a round trip, which is why parents beat votes.
     From LA all nine links measure 2.01-2.08× the probed UDP RTT.
  2. **Europe↔Asia traffic between the nodes goes through the US.** The nodes dial each other on their
     external addresses (the committee advertises `/ip4/34.x…/udp/49590/quic-v1`, ephemeral Premium-tier
     IPs); the latency probe measured internal addresses. For every Europe→Asia link the vote time equals
     2 × (RTT to LA + RTT from LA to the peer) within 7 ms (London→Tokyo 472 vs 474, Seoul 523 vs 527,
     Sydney 554 vs 549, Hong Kong 559 vs 560, Singapore 594 vs 601, Mumbai 724 vs 706; the Netherlands
     likewise), while Europe↔Americas and Europe↔Europe links are 2× their direct RTT. London's effective
     RTT to Mumbai is ~350 ms instead of the probed 149.
  London's sixth vote (Sydney) therefore returns at 2 × (137 + 138) ≈ 550 ms; with direct routing and
  one-RTT votes it would return at about 200 ms.
- **`max_header_delay` matters only for churn.** At 500 ms the max timer fires every round (92
  re-proposals per minute per node); at 1000 ms about 5. It does not change the round.
- **Under load every arm is execution-bound**, as §5 said: 1.22-1.41 rounds/s, 14.4-15.8 blocks/s,
  4.2-5.0 k tx/s, commit latency p50 1.65-1.75 s regardless of the timers. A3 is the fastest loaded arm
  and the only one whose loaded C p95 for Sydney stays under the round.
- **Side effects now explained.** The blasters pinned to London, the Netherlands and Mumbai submitted
  20-160 k transactions per arm against 280-740 k elsewhere and landed 51-95 %: their batches sit in
  headers that get cancelled, so the generator keeps re-sending the head of its queue. London's commit p95
  of 4.04 s in A4 was a late epoch-10 close (114 vote requests rejected with `Invalid epoch`), not a timer
  effect. No commit stall in any arm.

### 9.3 Predictions against measurements

| item | §5 / §6 predicted | measured |
|---|---|---|
| idle round A0 / A1 / A3 | ~400 ms | 550 / 538 / 530 ms |
| idle round A2 / A4 | ~460 / ~560 ms | 527 / 527 ms |
| every validator ≥ 99 % certified idle | yes | 8 of 10; London 7-50 %, Netherlands 0.7-21 % |
| Sydney C p50 | 366-370 ms | 423-427 ms, certifies 92.5-99.9 % |
| London / Netherlands C p50 | 335 / 332 ms | 556-564 / 580-585 ms |
| Mumbai C p50 | 287 ms | 449-467 ms (zone c, unprobed) |
| Montréal fastest | 358 ms | 406 ms; Seoul 264 and Tokyo 272 are fastest |
| A0 max 500 above the round | yes | no; fires every round |
| A2 Sydney referenced too late ~5 % | 95 % | 99.9 % |
| A4 leader shortcut costs four nodes ~5 % | 95 % | no loss seen |
| loaded regime execution-bound | yes | yes |

### 9.4 Revised recommendation and the decision for stage 2

No arm meets the §6 contract, and the failing criterion is the same in all five: the vote path, not a
timer. The two parameters that matter are settled:

- **`max_header_delay` 1000 ms, `min_header_delay` 250 ms, `max_batch_delay` 250 ms (arm A3)** is the
  fleet config to carry forward: fastest under load, least churn, no idle cost against A0.
- **Fastest cadence this geography supports today**: ~530 ms idle (1.9 rounds/s) with eight of ten
  validators certifying; ~1.4 rounds/s and ~15.8 blocks/s under load. With the vote path at one RTT, as
  the model assumed, the seventh certificate would be Singapore's at ~344 ms and the round ~450 ms with
  all ten certifying.
- **The only parameter that lets London and the Netherlands certify** is a `min_header_delay` that binds
  above their quorum time, ≥ 600 ms (round ≈ 600-620 ms, about 12 % slower). It was not an arm.

The levers, in order of value:

1. **Consensus traffic over internal addresses** (same VPC, Google's backbone): a harness change
   (committee addresses, firewall sources, the node's advertised address) that removes the US detour for
   Europe↔Asia. No new node image.
2. **One-RTT votes upstream**: `with_substream_upgrade_protocol_override(Version::V1Lazy)` on the swarm
   (one line in `network-libp2p/src/consensus.rs`). Caveat for mixed-version fleets: a peer without the
   protocol then surfaces as an I/O error instead of `UnsupportedProtocols`, so the peer-penalty and
   sync-capability paths must classify it. Halves every node's C.
3. With both, the model's assumption (C ≈ RTT to the sixth-nearest voter + ~70 ms) holds and the fleet
   round would be roughly 300-350 ms with all ten certifying. With neither, `min_header_delay` ≥ 600 ms
   is the only way London and the Netherlands certify.

Stage 2 (the 40-minute chaos run) waits on one choice: (a) do 1 and 2, re-run A3 as a short check,
then stage 2; (b) do 1 only and run; (c) run A3 as-is, recording London and the Netherlands at 1-50 %;
(d) run at min 600 ms. The node debug filter default now includes the vote-handler, negotiation and
connection targets, so whichever runs will show the voter side. Mumbai (74-90 % under load, 11-21 % not
committed in A2-A4) gets the same look.

Harness outcomes from the run, all first live uses: per-node `parameters.yaml` rewrite and log-filter
injection at deploy step 9; `params-apply.sh` stage test and five fleet-wide arms; blaster machine-type
fallback (Sydney's blaster was out of `e2-standard-2` on every blast); certification recorded as an
outcome with log snapshots for the four validators under 90 %; the local teardown gate. Gaps found:
`params-apply.sh` recorded nothing for an arm whose values were already in place (A0 was recorded by hand),
`propose-latency.py` read only the last container's log, and files written after teardown were missing
from the index. Fixes are in `benchmark/private/followups.md` and on the branch.

