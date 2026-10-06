status: done
completed sections: 1, 2, 3, 4, 5, 6, 7 (+ mapping, open questions)

# L1: why v03/v04/v10 could not certify round 1787 (r20261006-0053)

## Mapping (from "Certifier on node X has started successfully" + libp2p startup lines)
- v01 = DSaB3u5YWck3s4WdJH6nx9XXZyQ3uqduZw1h78m59Teb, primary peer 12D3KooWEp4YHNhG..., 10.168.0.37
- v03 = 5LVuvnirA7mM4qTcWoZfFDaRKnaMTBChkDrzJfwXeqmi, primary peer 12D3KooWKBHCNShG..., 10.152.0.25
- v04 = 2HvFWgXodJ55mXaMTKL6ZtPswLsj63XoRBFJt9VHWiv1, primary peer 12D3KooWFqyLqn8t..., 10.152.0.26
- v10 = 6ZkJCVcSgnEJZmk8iCJRdm1yZbXaitpdrWfpHk3owHAq, primary peer 12D3KooWRwFK3Uii..., 10.154.0.26
- v05 = F9AjwqW7FsKbVHgQQLgsESbKL4BAkYgXpMzjCThTi5XG, primary 12D3KooWKYVvx96n..., worker 12D3KooWKcKiLZoV..., 10.162.0.25 / 34.19.130.9; worker key qLSPwbMBJ4r8... (inferred)
- {4wcKJQb3, 7Ry6Gb2B, 8ftonHD8, C64y8KwK, FkhPAHJv} = {v02,v06,v07,v08,v09} (set membership proven by the 02:15:17 commit; individual mapping needs their logs)

## 1. v03 02:09:50-02:10:20
- certified after kill: r1768 (56.390), 1769 (59.657), 1773, 1776, 1778, 1780, 1783 (14.060), 1786 (16.297)
- r1787 header Fjioj78DrMLjQZNE proposed 02:10:16.242 (0 batches, 7 parents, exec:15463) 55 ms BEFORE own r1786 quorum
- parents (from 02:11:27.334 "inside propose_header"): C1786 of C64y8KwK, 7Ry6Gb2B, 4wcKJQb3, FkhPAHJv, 6ZkJCVcS(v10), DSaB3u5Y(v01), 8ftonHD8. No v05, no v03, no v04.
- v05 last cert r1767 (committed 02:10:01.25). Last commit 02:10:15.704 leader 1784.
- worker: quorum_waiter Outbound(Timeout) to qLSPwbMB from 02:10:09.011; AtCapacity batch-fetch from 22SKT6uW 02:09:53-54.

## 2. v04 / v10
- v04: r1787 GJd9JK26feeeWMxu proposed 02:10:16.244 (0 wbs, exec 15463), own r1786 quorum 16.299 (after). Same 7 parents.
- v10: certified every round 1767-1786; r1786 quorum 15.990; r1787 GGNgm1dzy6YQHy2d proposed 16.210 (1 wbs, exec 15463), same 7 parents (incl. own). Re-proposes every ~250 ms (1113/1113 gaps 250-299ms) while log says interval=500ms. v10 is the committed r1788 leader.

## 3. errors 02:10:15-02:15:20 (counts first..last)
v03: re-propose 598 (15.390..15:16.440); failed-to-get-vote Canceled 196 (17.754..15:16.441); Could not form 2 (11:27.334, 12:42.027); gc 30s 9; codec violation 25 @10:25.4-.5 (v05 peer ids only); quorum_waiter Timeout 4, NotConnected 5, DialFailure 65, UnexpectedEof 24 (all peer qLSPwbMB).
v04: re-propose 598; Canceled 241 (17.170..15:15.387); Could not form 4 (10:27.589, 11:06.202, 11:15.729, 12:03.860); codec 21; DialFailure 55; fatal request for requested vote 8 @15:17.574+ (epoch shutdown).
v10: re-propose 1191; Canceled 389 (17.162..15:16.001); Could not form 5 (10:33.228, 10:36.749, 12:37.141, 14:20.714, 14:36.045); codec 60; quorum_waiter Timeout 18, NotConnected 25, DialFailure 110, UnexpectedEof 22.
- Canceled lines: auth= is the LOCAL node; no peer named. Single error string ": Canceled". Coincide (<=10 ms) with a re-propose tick: v03 192/195, v04 232/241, v10 388/388. Burst max 5; each Could-not-form follows a 5-burst. No already-voted/equivocation/invalid/rejection text anywhere.
- Canceled also normal pre-kill (v01 164 in 01:50-02:09:55).

## 4. Same header each time
Digest never changes: Fjioj78DrMLjQZNE x196, GJd9JK26feeeWMxu x241, GGNgm1dzy6YQHy2d x389, exec stays 15463 though canonical head reached 15495 (~02:10:17.2) and 15513 (~02:10:18.6).

## 5. v01 contrast
- v01 r1787 DzrA2ndsjEHSucBz proposed 16.174, re-proposed 16.678/17.187, quorum 17.486. Parents unlogged but only 7 r1786 certs existed at 16.174 -> same set.
- v01 Recast votes 02:10:17-02:15:15: Fjioj (v03) 595, GJd9 (v04) 595, GGNgm (v10) 1188. v03/v04/v10 recast for each other ~595/1187. v01 has zero warn/error mentioning them.
- request arrival lag at voter: v03->v04 0-49ms, v03->v01 200-249ms, v03->v10 400-449ms, v10->v03 150-199ms, v10->v01 200-249ms.

## 6. Recovery (v03)
- v05 connections 02:15:08.922-02:15:12.370 (34.19.130.9); GRAFT from v05 02:15:15.516
- last r1787 re-propose 02:15:16.440 / Canceled 02:15:16.441; r1788 proposed 02:15:16.789 (own r1787 never certified)
- commit leader 1788 (v10) at 02:15:17.502, 30 certs, 23,236 tx; r1787 certs committed: 4wcKJQb3, 7Ry6Gb2B, 8ftonHD8, C64y8KwK, DSaB3u5Y, F9AjwqW7, FkhPAHJv
- epoch boundary detected 02:15:17.573; certifier shutdown; epoch 3 start 02:15:21.79

## 7. Verdict: see final report
## Chronic pre-kill evidence
quorum reached / proposed per 10 min: v03 01:2x 0/1564, 01:3x 0/1542, 01:4x 1/1533, 01:5x 84/1142, 02:0x 210/716; v04 same shape; v01/v10 ~93%.
v01 commit view certs per origin: v03/v04 0 in 01:3x/01:4x, 22 in 01:5x, ~110 in 02:0x vs 600-1500 for the other 8.
