status: done
completed sections: 1, 2, 3, 4, 5, 6, 7

# A2 — r20261006-0458 node-log analysis vs r20261006-0053

Authority map (0458): 01 Axu3aj, 02 2mMxp, 03 AUsMy, 04 67bzP, 05 BwAHN, 06 6deWF, 07 FgVe7,
08 D6kRy, 09 BYTZM, 10 2LRh9.

## 1. Certification rates
Raw cert_rate.py tables (10-min buckets): scratch A2/cert_new.txt, A2/cert_old.txt. NOTE its
"canceled" column counts EVERY "failed to get vote" line; in 0458 the 06:40/06:50 buckets (~360/~714
per validator) are NetworkError "Header … is too new for max round N" (v05 catching up), not Canceled.
cert_rate "commits" column counts leader_round= on 2 message types, so it is not a commit count.

Per validator, run window = preamble start..cooldown end (0458: 06:05:38-06:52:08; 0053:
01:48:06-02:34:36), mixed = 40-min mixed phase. v05 = pre-kill + post-restart logs. (scratch cmp.py)

| v  | 0053 run% | 0458 run% | 0053 mixed% | 0458 mixed% | re-prop 0053/0458 | Canceled 0053/0458 | too-new 0458 | noform 0053/0458 |
|----|------|------|------|------|-----------|----------|-----|-------|
| 01 | 94.2 | 97.1 | 94.1 | 96.5 | 3163/3134 | 322/42   | 699 | 2/1   |
| 02 | 94.5 | 96.9 | 94.5 | 96.8 | 3074/3087 | 330/31   | 699 | 2/2   |
| 03 | 20.1 | 47.1 | 23.6 | 60.4 | 3084/2901 | 1746/553 | 222 | 21/6  |
| 04 | 20.9 | 52.9 | 24.2 | 67.8 | 2961/2813 | 1772/474 | 220 | 19/8  |
| 05 | 85.2 | 98.1 | 82.7 | 97.9 | 2649/2149 | 813/14   | 0   | 29/1  |
| 06 | 99.3 | 98.3 | 99.3 | 97.7 | 3141/3091 | 156/10   | 699 | 1/1   |
| 07 | 93.3 | 90.3 | 93.1 | 87.7 | 3160/3081 | 415/82   | 699 | 7/1   |
| 08 | 94.3 | 93.4 | 94.1 | 91.8 | 3101/3029 | 346/70   | 695 | 4/4   |
| 09 | 95.0 | 97.6 | 95.0 | 96.9 | 3097/3061 | 353/27   | 696 | 4/0   |
| 10 | 94.1 | 96.9 | 93.9 | 96.2 | 3747/3079 | 752/23   | 699 | 9/0   |
Proposals per validator in run window ~3,190-3,260 both runs (v05 less: outage).
Canceled fleet total (run window): 7,005 -> 1,326 (-81%); excluding v03/v04: 3,487 -> 299 (-91%).

v03/v04 by load regime (from 10-min buckets):
- fast idle rounds (~375 ms/round, 0 re-proposals): 0458 05:30-05:59 v03 0/4,807, v04 0/4,807;
  06:50-07:09 v03 11/3,172, v04 9/3,172. 0053 01:20-01:49 v03 1/4,639, v04 1/4,639. => fix changed nothing here.
- under load (rounds ~0.7-1.2 s, re-proposals ~700/10min): 0458 06:10-06:39 v03 1,215/1,819 = 66.8%,
  v04 1,249/1,818 = 68.7% (bucket peak 74%/81.5%); 0053 02:00-02:29 v03 488/1,481 = 33.0%, v04 508/1,483 = 34.3%.
  => fix doubled their share under load.
- In fast buckets v03/v04 still log ~500-760 Canceled /10 min with 0 re-proposals: these are cancels
  by the NEXT-round header (new digest), i.e. the round advances (others' 7 certs) before v03/v04
  gather 6 remote votes. Latency-bound, not the re-propose bug.
- v10 (next-leader 250 ms window): re-proposals 3,747 -> 3,079 (now same as peers), Canceled 752 -> 23.
- non-AU fast-round share went 93-95% -> ~100% (0053's ~5-6% loss was the same cancel bug).
- v07/v08 slightly worse under load (06:20 bucket 87.0%/86.8%; mixed 87.7%/91.8% vs 93.1/94.1).

## 2. Outage 06:36:30-06:43:00 (v05 down 06:36:58.139-06:41:58.179)
Per 30 s (scratch outage.py; commits = "subdag committed" lines; v05errs = warn/error lines naming
v05's BLS key yk67mHU3UX…, peer ids 12D3KooWCeLw4a…/12D3KooWNZZ7RX… or worker key q1vUvDb49f…):
| 30 s from | v01 commits | v01 rounds | v01 quorum/props | v03 commits | v03 quorum/props | v01/v03 v05errs |
|---|---|---|---|---|---|---|
| 06:36:30 | 11 | 1011-1033 | 23/23 | 11 | 18/23 | 0/195 |
| 06:37:00 | 13 | 1034-1066 | 28/33 | 13 | 25/32 | 143/207 |
| 06:37:30 | 12 | 1067-1092 | 26/26 | 12 | 19/27 | 153/173 |
| 06:38:00 | 11 | 1093(e3) -> 1-28(e4) | 28/29 | 11 | 15/28 | 168/145 |
| 06:38:30 | 8 | 29-51 | 22/23 | 8 | 9/24 | 112/123 |
| 06:39:00 | 10 | 52-71 | 21/20 | 10 | 8/19 | 189/116 |
| 06:39:30 | 11 | 72-96 | 25/25 | 11 | 9/25 | 128/126 |
| 06:40:00 | 9 | 97-116 | 20/20 | 9 | 11/20 | 217/139 |
| 06:40:30 | 8 | 117-136 | 20/20 | 8 | 3/20 | 86/103 |
| 06:41:00 | 10 | 137-157 | 21/21 | 10 | 10/21 | 165/82 |
| 06:41:30 | 10 | 158-179 | 21/22 | 10 | 14/22 | 192/93 |
| 06:42:00 | 9 | 180-196 | 17/17 | 9 | 0/17 | 197/97 |
| 06:42:30 | 12 | 197-225 | 29/29 | 12 | 11/29 | 67/63 |
- No commit gap other than the epoch switch: last e3 commit 06:38:01.144 (leader 1092), first e4 commit
  06:38:10.670 (leader 2) on v01 = 9.5 s; never > 3 s between commits otherwise. Commit/round rate during
  the outage (8-13 commits, 17-33 rounds per 30 s) equals the pre-kill bucket (11/23): load-bound, not v05-bound.
- `no consensus commit happened`: 0 on v01 and v03. `Could not form a certificate`: v01 0, v03 1 (06:42:30).
- v03 certified 15-70% of its headers during the outage (vs ~70% before it): with v05 gone it needs
  6 of 8 remote voters. v01 ~100%. The chain had 7 full certifiers + partial v03/v04 and never ran dry.
- v05-directed errors: quorum_waiter "Network error, peer yk67… Outbound(Timeout), retrying" (first
  06:37:10 v01, 06:37:12 v03), "outbound IO failure … ConnectionLost(TimedOut)" 06:37:28,
  epoch-manager "failed to dial yk67…" from 06:38:07 (after epoch switch), worker "failed to fetch batches".
  v03 already logged worker "failed to fetch batches … PeerMissing" for q1vUvDb49f before the kill.
- Epoch boundary (registry 06:37:57 = 1791268677): "epoch boundary detected epoch=3 commit=1791268679"
  v01 06:38:01.170, v03 06:38:01.354 => detected 4.2 s after the boundary instant; triggering commit's
  timestamp 06:37:59 (2 s after), detected 2.2 s after that (commit of leader 1092 at 06:38:01.144).
  closing-epoch registry event v01 06:38:07.65 / v03 06:38:05.85; "epoch boundary success" v01 06:38:09.24 /
  v03 06:38:07.13; "Starting epoch" v01 06:38:09.49 / v03 06:38:07.37; first e4 header v01 06:38:09.56
  (round 1, 10 parents), first e4 quorum v01 06:38:10.04 (r2) / v03 06:38:09.66 (r1).
- Parents per own header while v05 down (06:37:00-06:42:00): v01 7:216 8:13 9:9 10:1; v03 7:201 8:24
  9:12 10:1 => >90% of headers carried exactly the 7-parent minimum (only epoch round 1 had 10).

## 3. v05 recovery (restart -> certifying = 12 min 34 s)
- Pre-kill log ends 06:36:30.41 (saved 28 s before the kill): last own header r1011 e3 (1 batch, 7 parents),
  last quorum r1010 06:36:30.23, last commit leader 1008 06:36:29.66 (output 4455, 22 batches, 5,846 tx).
  Normal: quorum on every header, "asked to propose a header that is already certified … re-publishing" after
  each re-propose tick. The 06:36:30-06:36:58 tail is not in any telcoin log (unit-stdout not read).
- 06:41:58.47 start (systemctl 06:41:58.179). 06:41:58.63-06:42:06.07 pack WAL recovery epoch-3 (480
  records, 7.44 s); torn tails truncated (records 1,045,213 B, certs 1,048,140 B). Engine from block 27945.
- 06:42:08.08 Starting epoch 3; 06:42:09.75 "epoch already closed by its committee; replaying it without
  the vote-window check" epoch=3; 06:42:09.79 DAG restored from GC round 980; 06:42:09.80 CvvActive;
  re-proposed stale e3 r1032 header -> 06:42:09.81 "fatal request for requested vote … Invalid epoch. Peer
  proposed epoch 3, but expected 4" (10 lines) -> certifier shutdown 06:42:09.82.
- 06:42:10.07 epoch 3 again as CvvInactive (follower). 06:44:35 "catching up consensus blocks" 4466->4604.
  06:45:28.15 epoch-3 boundary detected (7 min 31 s after the real one); 06:45:37.96 boundary success;
  06:45:38.16 epoch 4 CvvInactive, catch-up 4492->4636 (144); 06:52:06 4636->4976 (340);
  06:54:30.25 4976->5165 (189); 06:54:30.67 5165->5166 (1).
- 06:54:31.44 epoch 4 CvvActive, DAG from GC round 1354, certifier started 06:54:31.47. First header =
  stale r439 (10 parents) -> 9x "fatal … Header … for round 439 is too old for max round 1406". 06:54:31.95
  first commit seen (leader 1406) + header r1410 (1 batch, 7 parents); 06:54:32.65 first own quorum r1412.
  After that ~100% certification (cert_rate 06:50 bucket 860/863, 07:00 1597/1596).
- Why so slow: catch-up was EXECUTION-bound. v05 executed ~850-935 blocks/min (14-15.6 blocks/s,
  "next block executed" per minute 06:45-06:53) while the loaded chain produced ~12 blocks/s
  (27945 -> 36577 between 06:36:30 and 06:48:21). It gained only ~3 blocks/s, and caught up only because
  the chain stopped producing blocks at 06:48:21 (see s6): its 501 "skipping execution for empty
  non-epoch-closing output" lines are all at 06:54. "fetching consensus from peer" 9-21/min until 06:47,
  79/min after the load stopped.
- While CvvInactive, v05 still answered vote requests with refusals: peers log "failed to get vote …
  NetworkError … Header X for round N is too new for max round M" — on v01 06:45 30, 06:46 74, 06:47 58,
  06:48 244, 06:49-06:53 ~316/min, 06:54 162 (M jumps 482..1224 in the last 3 s). Harmless (quorum came
  from the others) but ~2 extra errors per header fleet-wide for 9 min. 0 such lines in 0053.
- Compare: 0053 restart->new-digest proposal 16 s (02:15:00 -> 02:15:16.3, same epoch because the chain had
  stalled); 29 Sep 25 min. This run sits between: the epoch it died in had closed, so it replayed epoch 3,
  then followed epoch 4 at execution speed.

## 4. New or worse (warn/error, all 11 nodes, run window 46.5 min both runs; /h = x1.29) (scratch errs.py)
Totals: 0458 E 14,760 / W 84,373; 0053 E 8,123 / W 46,930. The growth is all v05-recovery and worker noise:
| message (normalised) | 0458 | /h | 0053 | where |
|---|---|---|---|---|
| W re-proposing last header after max delay | 29,425 | 37,968 | 31,177 | all, ~3.1k each (v10 3,747 -> 3,081) |
| W failed to fetch batches from peer, trying next | 26,407 | 34,074 | 7,636 | v03 23,148: PeerMissing to observer worker q1vUv… 17,420 + v06 "peer denied sync batch request: AtCapacity" 5,504; 0053 same pattern on v04 (5,585 to old observer) |
| W Network error, peer X: Outbound(DialFailure), retrying | 10,628 | 13,714 | 784 | quorum waiters on every validator (v06 1,920 … v10 1,323) — dialing dead/catching-up v05 |
| W process_gossip Certificate(CertificateManagerOneshot) | 5,903 | 7,617 | 27 | v05 5,889 (catch-up) |
| E fatal request for requested vote :: too new for max round | 5,330 | 6,877 | 0 | every validator, v05 refusing while CvvInactive (s3) |
| E failed to get vote :: NetworkError … too new for max round | ~5,330 | | 0 | same events, requester side |
| W max delay interval expired for round N | 3,014 | 3,889 | 3,481 | all |
| E RPCError … Failed batch validation: Invalid epoch | 2,699 | 3,483 | 396 | v01 476, v10 421 … (batches to v05 still in epoch 3) |
| W process_gossip BatchEpochMismatch / InvalidEpoch / TooOld | 2,621 / 1,575 / 682 | | 233 / 0 / 178 | v05 only |
| W Repropose N batches in undelivered headers [N] | 1,174 | 1,515 | 1,412 | v07/v08/v04/v03 |
| E failed to get vote :: Canceled | 1,326 | 1,711 | 7,005 | v03 553, v04 474, rest 10-82 |
| W no consensus commit happened … certificate fetching | 0 | 0 | 81 | |
| E Certifier error / Could not form a certificate | 24 | 31 | 98 | v04 8, v03 6, v08 4 |
Only in 0458 (besides the v05-recovery lines): W "failed to dial X: Dial error: dial condition …
PeerCondition::Disconnected" 123 (16 per validator, after the epoch switch, v05 dead); W "timeout reading
sync batch frame" 95 (v02 only); W "no readable sync request frame" 4 (v08); W "Could not find consensus
output (we may be catching up)" 3 (observer). None points at the certifier change.
"asked to propose a header that is already certified … re-publishing": 12,720 vs 18,362 (present in both;
v03 250, v04 403 vs ~1,400-1,900 for the others).
Whole-file scan, both runs: panic 0, FatalDBFailure 0, AlreadyVoted 0, equivocat* 0, "invalid vote" 0.

## 5. Verdict
1. The fix did what ROOT-CAUSE predicted for the re-propose bug. Canceled went from 7,005 to 1,326 fleet-wide
   (-81%; -91% without v03/v04). v10 went from 752 to 23 Canceled, and its re-proposals from 3,747 to 3,079.
   Non-AU validators went from 93-95% to ~100% in fast rounds. Under load, v03/v04 went from 33/34% to 67/69%
   (run window 20/21% to 47/53%).
2. Killing v05 59 s before the boundary no longer stalls the chain. There were 8-13 commits every 30 s,
   0 "no consensus commit" lines (0053: 81), and the boundary was detected 4.2 s after it.
   The epoch switch paused commits for 9.5 s.
3. Still open: v03/v04 certify 0% whenever rounds are fast (~375 ms): 0/4,807 each in 05:30-05:59, and
   0 of ~158 headers/min in 06:49-06:52. The fix cannot help here: the next round's header (a new
   digest) supersedes theirs first. Also, ~1/3 of their certificates never commit (66%/69% vs v07 96.5%).
4. Consequence: the 06:48:21-06:54:33 inclusion gap. Once only blasters 03/04 were sending, no batch
   entered a certificate. Commits had 14 certs from the 7 near validators, and 480 empty outputs were skipped.
5. v05 took 12 min 34 s from restart to certifying (0053: 16 s). It died in a closed epoch, so it replayed
   epoch 3 and then followed epoch 4 at its execution limit (~14.5 blocks/s against ~12/s produced).
   Meanwhile it refused votes ("too new for max round", 10,658 error lines).
6. No regression traced to the fix: 0 panic / FatalDBFailure / AlreadyVoted / equivocation / invalid vote;
   Could-not-form 98 -> 24. Slower rounds = execution ceiling (~14-16 blocks/s) reached earlier in the run.

## 6. Inclusion gap 06:48:21-06:54:33 (scratch gap.py on 06:47:30-06:55:30, orphan.py)
Per minute (v01 view of commits; v03/v04 own headers):
| min | v03 props (w/ batches, batches) / quorum | v04 quorum | v03 sealed batches (tx) | subdags | certs/subdag | non-empty outputs (batches, tx) | skip-empty | blocks | committed certs from v03/v04/v05 |
|---|---|---|---|---|---|---|---|---|---|
| 06:47 | 15 (12, 33) / 13 | 14 | 24 (6,931) | 7 | 16.1 | 7 (423, 127,941) | 0 | 423 | 10/11/0 |
| 06:48 | 122 (23, 42) / 19 | 19 | 31 (10,459) | 55 | 16.0 | 12 (106, 33,393) | 43 | 106 | 19/20/0 |
| 06:49 | 159 (12, 12) / 0 | 0 | 12 (3,494) | 80 | 14.0 | 0 | 80 | 0 | 0/0/0 |
| 06:50 | 158 (0, 0) / 0 | 0 | 0 | 79 | 14.0 | 0 | 79 | 0 | 0/0/0 |
| 06:51 | 158 (3, 3) / 0 | 0 | 3 (904) | 79 | 14.0 | 0 | 79 | 0 | 0/0/0 |
| 06:52 | 158 (3, 3) / 0 | 0 | 3 (1,077) | 79 | 14.0 | 0 | 79 | 0 | 0/0/0 |
| 06:53 | 157 (19, 50) / 1 | 1 | 17 (4,335) | 79 | 14.0 | 0 | 78 | 0 | 1/1/0 |
| 06:54 | 146 (39, 168) / 10 | 8 | 32 (10,182) | 72 | 14.8 | 10 (67, 21,519) | 62 | 67 | 5/0/58 |
| 06:55 (30 s) | 80 (0, 0) / 0 | 0 | 0 | 40 | 15.9 | 0 | 40 | 0 | 0/0/80 |
(v04 sealed 40/44/3 batches 06:47/48/49, then none: blaster 04 stopped 06:50:21.)
(a) v03/v04 own headers: 0 quorum in 06:49-06:52 on 158 headers/min each, 1 at 06:53. Rounds ran at
  ~2.6/s (380 ms) once the 7 near generators stopped = the idle regime where v03/v04 certify 0% (s1).
  Their headers did carry batches when they had any (v03 3-50 per minute, 10-batch headers repeated
  via "Repropose N batches in undelivered headers"). So the batches never entered a certificate at all.
(b) Commits continued (79-80 subdags/min on every validator); each had exactly 14 certificates = 7 origins x
  2 rounds, all from v01/02/06/07/08/09/10 ("certificate committed … origin=" lines; 0 from v03/v04/v05
  06:49-06:52). Last non-empty output before the gap #4689 06:48:22 (leader 438, 1 batch, 391 tx); then
  480 empty outputs logged "skipping execution for empty non-epoch-closing output" (no block); first
  non-empty after #5171 06:54:33.75 (leader 1414, 3 batches, 1,128 tx).
  Parent-reference hypothesis, tested over the whole run: v03 certified 1,545 headers, only 1,019 (66%)
  ever committed; v04 1,197/1,730 (69%); v07 11,560/11,984 (96.5%). In the gap window v03 6/11, v04 1/9.
  So ~1/3 of the far validators' certificates are orphaned (not in any leader's causal history), BUT in
  06:49-06:53 the binding cause is upstream: there were no v03/v04 certificates to reference.
(c) Worker side on v03: "batch sealed" counts above (3-17 batches/min in 06:49-06:53 although blaster 03
  sent until 06:57:40 — consistent with the generator's in-flight window being full of unlanded tx; node
  logs cannot confirm). Quorum-waiter success and batch votes are not logged at info (only failures: none
  on v03 in the window); a batch appearing in a header implies it reached worker quorum. Other primaries'
  batch fetches are not logged on success; v01 logged no fetch failures in the window.
(d) 06:54:30: v05 catch-up hit distance 1 (06:54:30.67), CvvActive 06:54:31.47, proposed r1410 (1 batch)
  06:54:31.95 and r1412 (2 batches) 06:54:32.45 from its own pool, certified at once -> output #5171
  (leader 1414, 3 batches = v05's) at 06:54:33.75 -> block #36578. Rounds then slowed for 20 s (v01 per 10 s:
  26 -> 21, 20 headers; re-proposals 2 -> 6, 5); in exactly those 20 s v03 got 10 quorums (r1418-1426,
  10-batch headers) -> outputs #5172-#5183 06:54:34-06:54:47, 67 batches / 21,519 tx total. From 06:54:50
  rounds back to 26-27/10 s and v03 back to 0 quorum. So the release was v05's own batches + a 20 s slowdown,
  not v05 pulling v03's old certificates in (v03 had none to pull).
Logs CANNOT show: which voters answered / vote latency per voter, which parents each header referenced
  (only num_parents), successful batch syncs or worker quorum acks, tx pool contents/rejections.

## 7. Rounds slower under load (scratch rounds.py, bucket5.py, sealed.py)
Pre-kill mixed windows: 0458 06:09:08-06:36:30 (27.4 min), 0053 01:51:36-02:09:48 (18.2 min).
| metric | v01 0458 | v01 0053 | v07 0458 | v07 0053 |
|---|---|---|---|---|
| rounds/s, commits/s | 1.05, 0.50 | 1.50, 0.65 | 1.05, 0.50 | 1.50, 0.65 |
| max delay expired /min | 7.6 | 8.0 | 7.9 | 9.2 |
| re-proposals /min | 72.1 | 57.1 | 69.1 | 55.9 |
| parents 7/8/9/10 | 79/12/7/3% | 86/12/2/0% | 80/11/6/3% | 85/13/1/0% |
| propose->own quorum p50/p95 ms | 339/1042 | 291/915 | 579/1340 | 308/962 |
| own quorum->next propose p50/p95 ms | 360/1262 | 157/941 | 217/1042 | 133/890 |
| batches/header (share with batches) | 1.76 (71%) | 0.79 (34%) | 1.33 (57%) | 0.47 (25%) |
| per output: certs / batches / tx | 17.1 / 29.2 / 8,430 | 17.4 / 18.8 / 6,248 | same | same |
| blocks executed /min | 874 | 729 | 876 | 729 |
| exec latency (output ready -> canonical head) p50/p95 ms | 5,184/9,953 | 1,782/6,734 | 4,368/8,342 | 1,800/6,430 |
Fleet sealing in the windows: 0458 878 batches/min, 253,661 tx/min (289 tx/batch); 0053 732, 243,896 (333).
No new wait lines: no "missing parents"/"Waiting for"/certificate-fetch lines in either run's window.
5-minute buckets (v01; v07 same shape) show rounds track execution saturation in BOTH runs:
| 0458 | rounds/s | blocks/s | prop->quorum p50 | exec p50 | 0053 | rounds/s | blocks/s | prop->quorum p50 | exec p50 |
|---|---|---|---|---|---|---|---|---|---|
| 06:05 | 2.01 | 14.4 | 309 | 1,700 | 01:50 | 2.09 | 8.4 | 289 | 595 |
| 06:10 | 1.40 | 16.3 | 309 | 1,899 | 01:55 | 1.72 | 10.6 | 289 | 1,011 |
| 06:15 | 1.18 | 14.8 | 311 | 5,068 | 02:00 | 1.29 | 14.4 | 295 | 2,572 |
| 06:20 | 1.06 | 14.0 | 351 | 4,761 | 02:05 | 1.11 | 14.2 | 310 | 5,988 |
| 06:25 | 0.81 | 14.1 | 490 | 6,169 | (02:10 kill/stall) | | | | |
| 06:30 | 0.79 | 13.7 | 525 | 9,301 | 02:25 | 0.73 | 13.2 | 392 | 6,132 |
Execution tops out at ~14-16 blocks/s (one block per batch) in both runs (v05's catch-up also maxed at
14-15.6 blocks/s). 0458 reached that ceiling at 06:05 (preamble already 14.4 blocks/s) and stayed there
the whole window; 0053 ramped 2.7 -> 14 blocks/s through 01:45-02:05 and was killed at 02:09:55, so its
pre-kill average includes ~15 min of unsaturated 1.7-2.1 rounds/s. At equal block rate the runs match
(06:20 1.06 rounds/s vs 02:05 1.11; sustained 0.72-0.84 vs 0.73).
Verdict s7: mostly (iii) — rounds slow when execution is saturated (exec p50 5-9 s, 14 blocks/s), plus
a window artefact. Not (i): fewer 7-parent headers than 0053 and no more max-delay expiries. (ii) only
partly: certification of fast validators slows with exec load in both runs; v07 is slower in 0458 at
saturation (577-923 ms vs ~312 ms p50), v01 a little (351-525 vs 310). The logs cannot show WHY execution
load slows voting (CPU contention vs voters gating on the header's exec NumHash) — needs code/metrics.

## Working notes
- v05 pre-kill log ends 06:36:30.74 (saved 28 s before the 06:36:58.139 kill); last 28 s not in any telcoin log.
- manifest commit_stalls: 06:48:31-06:52:04 block 36577 (open). Headers at 06:50-06:54 all carry
  exec NumHash number 36577 -> execution head frozen while consensus kept committing? CHECK in s4.
- v05 restart: engine from block 27945; "fatal request for requested vote … Invalid epoch" at 06:42:09.
