status: done 02:59Z (row 10 left pending: before 03:26Z; rows 3,9 staking watch; 11,12,15 not VA)

unit VA: read-only verification rows of runbook section 10.
raw outputs: tasks/l2/w3/v/

completed rows:
- row 1 done (snapshots snap-0..5.json, postcheck-admission-rpc.txt rc=0)
- row 2 done (r2-series.txt, r2-analysis.txt: drop +501 for txgen N=500, accept +3341 for V2 N=3000, baseline 158/s accept 1.1/s drop)
- row 4 done (r4-*.txt, postcheck-binds-public.txt 38 checks 0 failed)
- row 5 done (r5-*.json: public answers on node1-5 all Observer + rpc-6 key 26LkT9gp)
- row 6 done (r6-records-grep.txt; snapshot entries carry no URL)
- row 7 done (r7-receipts.txt status 1 x3; r7-analysis.txt queued +495 requeued +43, worker fwd gw0 +123 gw1 +31 gw2 +247 gw6 +137, gw4 no worker series)
- row 8 done, verdict not verified (300x 200 in 4.28 s = 70/s; no rate_limited series; query fwd 311->616; txgen 200 at +0.84 s)
- row 13 done (r13-check-node-3/6.txt: rc 0 both, all OK, 0 warn; no P2P committee section; literal $(cat ...) in Bootstrap peers line)
- row 14 done (r14-release-verify.txt rc=0 VALIDSIG 95A38484...9FAE47 over 5 names)
- row 10: pending, 02:57Z < 03:26Z
- results file written: tasks/verification-l2-2026-11-17.md

order: 1, 2, 4, 5, 6, 7, 8, 13, 14, then 10 if after 03:26Z, then write tasks/verification-l2-2026-11-17.md
