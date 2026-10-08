status: done
completed sections: 0-mapping, 1, 2, 3, 4, 5, 6, 7, 8

## 0. Mapping (from "Certifier on node X" + own "Recast vote" voter id)
v01=DSaB3u5Y.. v02=7Ry6Gb2B.. v05=F9AjwqW7.. v06=C64y8KwK.. v07=4wcKJQb3.. v08=FkhPAHJv.. v09=8ftonHD8..
{03,04,10} = 2HvFWgXo.., 5LVuvnir.., 6ZkJCVcS.. (no log of theirs in scope; cannot tell which is which)
v05 worker peer (quorum_waiter) = qLSPwbMBJ4r8... (only peer erroring after the kill)
NOTE: logs in scope start at step-9 restart (01:17:05..01:19:56); v05pre ends 02:09:51.57 (3.7 s before kill);
observer telcoin.log starts 02:20:04 (pre-restart obs log NOT in scope -> no observer view of the stall).

## 1. Baseline. Windows: A = log start..02:09:55.287 (~50-52 min), B = kill..02:10:15, C = 02:10:15..02:15:20
failed to get vote (all ": Canceled" except 2 NetworkError on v02 at 01:18:58 startup):
 v01 A=355 [01:17:35..02:09:45] B=1 C=0 | v02 A=383 B=6 C=0 | v06 A=61 [01:50:51..] B=1 C=0
 v07 A=357 B=9 C=0 | v08 A=392 B=0 C=0 | v09 A=294 B=4 C=0   (v01 ~7/min, every minute; burst 16-24/min 02:07-02:09)
Could not form a certificate: v01 4, v02 4, v06 1, v07 4, v08 5, v09 2 in A; 0 in B; 0 in C
re-proposing last header: A ~1340-1506 per node (~28/min), B 23-29, C 597-599 (=every 500 ms for 300 s)
max delay interval expired (non-reprop): A ~470-497, B 2-5, C 1
asked to propose a header that is already certified: A 660-1251, C 596-599 (every 500 ms)
Recast vote: A 5300-6060, C ~2397 (8/s)
no consensus commit happened for 30s: A=0, B=0, C=9 on every node
vote-timeout wording: only startup "Vote timeout set to N ms" (3x). No vote timeout fired anywhere.
quorum_waiter "Network error, peer qLSPwb..": A=0 on all six; first 02:10:05.3-02:10:08.9 (10-14 s after kill);
 window to 02:15:00: 131-201 per node; RPCError qLSPwb 27-31 per node 02:15:22-02:15:35 (v05 back)
C window other net: Outbound(DialFailure) ~80-100, ConnectionLost(TimedOut) 36-58, UnexpectedEof 16-30, "outbound IO failure" 41-61
 (A: "outbound IO failure" 0-7, "epoch pack sync exchange failed" 9-12)
Verdict: Canceled vote failures + reproposals are COMMON in normal operation; noCert rare; network errors and
30 s no-commit absent before the kill.

## 7. chaos-remote.log (raw)
BEGIN v05 1791252595.287 = 02:09:55.287Z ; END rc=0 02:09:55.666 (output "telcoin" / "inactive")
BEGIN v05 1791252899.816 = 02:14:59.816Z ; END rc=0 02:14:59.854 (output "active")
BEGIN obs11 1791253201.827 = 02:20:01.827Z ; END rc=0 02:20:04.191 (output "active")

## 2. v01 round-1787 certification (status: done)
v01: 1784 prop 14.243/q 15.154; 1785 prop 15.331 (7 parents)/q 15.621 (0.29 s); last commit 15.633 leader_round=1784 (leader=V07, 15 certs);
 1786 prop 15.669/q 15.962 (0.29 s); 16.173 "max delay interval expired for round 1786"; 1787 prop 16.174 num_parents=7 num_batches=1;
 re-proposed 16.678, 17.187 (twice BEFORE certifying); 17.486 "quorum reached round=1787 voting_power=7 quorum_threshold=7 num_votes=7"
 => delta 1.312 s (vs 0.29 s for 1785/1786). Individual votes not logged at info. Own 1787 header digest DzrA2ndsjEHSucBz.
 then 02:10:17.699..02:15:16.262: every 500 ms "re-proposing last header ... round 1787" + "asked to propose a header that is already certified DzrA2ndsjEHSucBz, skipping proposal and re-publishing" (598/596x)
Other five: v02 prop 16.174 q 17.189 (1.015 s, 1 reprop 16.678); v06 16.178->17.528 (1.35 s, reprop 17.046); v07 16.216->17.573 (1.357, reprop 17.086);
 v08 16.222->17.574 (1.352, reprop 16.963); v09 16.210->17.569 (1.359, reprop 16.931). All 1787 headers 7 parents.
 All six: "max delay interval expired for round 1786" at 16.173-16.222 (also universal at 1768 ~09:57 and 1778 ~10:09; 1778 leader round never committed).
Cert inventory: NOT logged (no per-cert receive/insert lines at info). Proxy = Recast votes during stall (all six identical):
 r1787 XA 597x, XB 597x (every 500 ms), XC 1191x (every 250 ms) from 02:10:17.2-17.7 to 02:15:16.5-16.9; V01/V06/V07/V08/V09 r1787 recast once/twice ~17.2-17.5 only.
 => 03/04/10 kept re-requesting votes for their 1787 headers for 5 min and every survivor answered with a recast (same vote digest each time).
Commit at 02:15:17.433 (leader_round=1788, 30 certs, min_round=1784) shows DAG content:
 1784: V09 XC V08 V02 V06 V01 (+V07 leader earlier) ; 1785: V08 V09 V06 V02 V01 V07 XC (7; no XA/XB/V05)
 1786: V09 V06 XA V07 XC V02 V08 XB V01 (9; no V05) ; 1787: V06 V09 V07 V08 V02 V01 V05 (7 = six + V05) ; 1788: XC (leader)
 V05 last committed cert before kill: round 1767 (commit 02:10:01.25).
Leaders committed: 1754 V06,1756 V01,1758 V05,1760 V08,1762 V06,1764 V07,1766 V09,1768 XC,1770 V02,1772 V09,1774 V06,1776 V01,(1778 skipped),1780 V08,1782 V06,1784 V07,(1786 skipped),1788 XC

## 3. 02:10:15-02:10:20 (status: done)
All six: 1785 prop 15.26-15.33 q 15.49-15.63; commit leader_round=1784 at 15.58-15.63; 1786 prop 15.67-15.71 q 15.86-16.03;
 "max delay interval expired for round 1786" 16.173-16.222 on all six (proposer waited full 500 ms at even round 1786 => 1786 leader cert absent/late);
 1787 prop 16.17-16.22 (7 parents). Same universal max-delay at 1778 (~02:10:08-09) -> 1778 leader never committed (1780 commit subsumed it).
DAG per 02:15:17 commit: V05 has NO cert in rounds 1768-1786 (last 1767). 1785: XA, XB absent from causal history; 1786: only V05 absent.
No "missing parents"/"synchroniz"/"fetching" lines at info on any survivor in the stall (only grep hits = epoch-change task shutdown at 02:15:21).
"no consensus commit happened for 30s, triggering certificate fetching." (warn primary::gc) 9x per node, exactly every 30.00 s:
 v01 02:10:47.660, 02:11:17.661, ... 02:14:47.668; v02 .655..; v06 .626..; v07 .584..; v08 .582..; v09 .588..
 Fetcher outcome: NO "certificates fetched" line during stall on any node (that line IS logged when it gets something: v01 02:08:12.848 num_certificates=4 lower_bound=1604; 02:17:44.912 6 certs). => fetches returned nothing; peers/rounds not logged at info.

## 4. Epoch boundary (status: done)
02:09:30-02:16:00, all six: only epoch line before 02:15:17 = periodic "failed to retrieve epoch from a peer 2: Could not get the epoch record!" (~10/min, same rate pre-kill: background).
No "stop proposing"/"last round"/closing/concludeEpoch lines before the stall. First: "epoch boundary detected epoch=2 commit=1791252916 epoch_boundary=1791252637"
 at 02:15:17.436 (v09) .441 (v07) .455 (v08) .477 (v06) .494 (v02) .497 (v01); commit ts=02:15:16, boundary=02:10:37 (279 s late).
 Then "closing epoch emitted registry event" 02:15:19.8-19.98, "epoch boundary success" 02:15:21.2-21.4, "Starting epoch" 21.47-21.68, "reached quorum on epoch close" 23.11-23.18.
Earlier boundaries detected on time: epoch0 01:30:37.819 commit=boundary=1791250237; epoch1 01:50:38.550 commit=boundary=1791251437;
 later epoch3 02:35:18.137 commit=boundary=1791254116 (02:35:16; i.e. schedule shifted ~4m39s).
Detection is commit-driven (compares committed subdag timestamp to boundary) -> no commit = no detection. Observer: no log in scope for that window.

## 5. v05 (status: done)
PRE-KILL: v05pre.log ends 02:09:51.572 ("header proposed round=1764 num_parents=7") = 3.7 s before the kill (snapshot taken first).
 Last 60 s (02:08:51.5-02:09:51.6): 59 headers r1706-1764, 58 quorums, 28 commits, 71 reprops, 7 Canceled vote fails  == v01 (58/56/28/71) and v07 (59/53/28/72): on schedule (~1 round/s).
 Last commit in its log: 02:09:50.825 leader_round=1762. Survivors' DAG has V05 certs through r1767 (committed 02:10:01.25), none 1768-1786.
POST-RESTART (v05.log starts 02:15:00.121):
 00.329 consensus_pack "pack opened unclean or inconsistent; replaying data-file WAL to recover" (epoch-2) -> 07.953 "pack WAL recovery complete" records=764 elapsed_ms=7623
 07.997 epoch-db "truncating torn tail of unclean log" records (1,046,354 B) + certs (1,048,276 B); 08.021 "Engine stated from block 15197"
 08.39-09.8 connections to all peers; 09.844 "startup epoch record sync finished"; 09.850 "Starting epoch"
 09.878 "Waiting for execution of replayed consensus EWQPCNTf.." -> canonical heads r1762 (12.16) r1764 (13.85) r1766 (15.40) -> 15.405 "Confirmed execution of replayed consensus"
 15.433 "Recreating dag from last GC round: 1716"; 15.459 "Dag is restored and contains 14 certs for 51 rounds" (r1765-1767 incl own 1766/1767)
 15.4587 "subscriber starting in mode node_mode=CvvActive"; 15.460 "reproposing header authority=V05 current_round=1767" -> already certified 996gzi3H..
 15.80-15.96 process_gossip Certificate(Pending(..)) for DzrA2nds(V01 r1787) F7ruREb5(V06) DDsRQFTr(V07) 9nz3r4gq(V08) 13xpkHuM(V09) 8SybxC7n(V02 presumably) = the six r1787 certs
 16.056 cert-pack torn tail truncated; 16.137-16.140 catch-up subdag commits leaders 1768,1770,1772,1774,1776; 16.138 "own committed header not found at round 1766, probably because of restarts."
 16.139 "certificates fetched fetch_latency_ms=337 num_certificates=154 lower_bound=1716"  <- how it got the 9 r1786 parents
 16.302 "max delay interval expired for round 1786"; 16.303 "header proposed round=1787 num_batches=2 num_parents=9"; 16.677 quorum r1787 (0.374 s)
 16.680 prop 1788 (7 parents) q 16.862; 17.084 prop 1789 q 17.265; 17.467 prop 1790 -> "fatal request for requested vote ... Failed to return pending certificate manager result" from all 9 peers (they had closed epoch 2 at 17.44-17.50); "Could not form a certificate for header 2tAGHNp5.." 17.907, repeats ~20/s
 own commits (catch-up): 18.951 leader 1780, 23.351 1782, 25.155 1784, 25.157 1788; 32.174 "epoch boundary detected" (same commit=1791252916); 35.858 boundary success; 36.061 Starting epoch (epoch 3) ~14 s after the others; 36.123 r1 epoch3 10 parents; 37.547 first epoch-3 commit
 "recover/replay" wording: WAL recovery + replayed consensus only; no "catch up" wording. 1274 "failed to fetch batches from peer ... AtCapacity / sending stopped" warns 02:15:15-02:15:30.
Recast-vote id == header digest (v02 "Recast vote DzrA2ndsjEHSucBz: V1787(V02, V01" = v01's own 1787 header). XA/XB/XC digests constant for 5 min on all survivors:
 XA GJd9JK26feeeWMxu, XB Fjioj78DrMLjQZNE, XC GGNgm1dzy6YQHy2d => 03/04/10 re-sent the SAME header; every survivor re-sent its vote each time.

## 6. Observer (status: done)
obs telcoin.log starts 02:20:04.454 (engine from block 19263, epoch 3); 02:20:06.330 node_mode=Observer, "Starting subscriber: Follower";
 02:20:06.895 bulk epoch-3 download failed -> backwards download; first "next block executed" 02:20:09.199 (#19264). 311 blocks by 02:20:30, 853 next minute.
Validators unaffected: v01/v07 commits/min 23 (18:30-19:30), 24 (19:30-20:30), 26 (20:30-21:30); only trace = new inbound connections at 02:20:04.65.
(Unrelated aside: 10.15 s commit gap 02:18:00.68-02:18:10.83 on v01/v07, slow rounds 141-146 epoch 3, not a stall.)

## 7. chaos-remote.log (status: done)
BEGIN/END are printed on the remote host. kill: BEGIN 02:09:55.287 END 02:09:55.666 (0.38 s; prints "telcoin","inactive") plan 02:09:38 => +17.3 s
restart: BEGIN 02:14:59.816 END 02:14:59.854 (0.04 s; "active") plan 02:14:38 => +21.8 s; node log 02:15:00.121
observer: BEGIN 02:20:01.827 END 02:20:04.191 (2.36 s; "active") plan 02:19:38 => +23.8 s (END +26.2); obs log 02:20:04.454
=> all lateness is before BEGIN (harness->remote: ssh/IAP setup, preceding sequential steps); the remote actions themselves are sub-second (obs 2.4 s). File cannot say which.

## 8. Verdict: see final report.
