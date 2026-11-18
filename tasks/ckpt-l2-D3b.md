status: done (steps 14-19; step 20 and S1 not run)
unit: D3b (devnet launch 2, deploy steps 14-19 on the live fleet)
updated: 2026-11-18T02:19:14Z

completed sub-steps:
- A0 token-ok 01:22:54Z; token watcher pid 1401899 (tasks/l2/w3/d3b/token-watch.log)
- A1 STARTED 01:22:54Z: ./devnet-deploy.sh --yes --only 14 (log s14.log, rc s14.rc). DO NOT RE-RUN; if s14.rc missing, wait on it.

- A1 DONE 01:39:53Z rc=0 (COORDINATED_START spread_secs=0, A1-A6 all six)
- A2 DONE 01:40:02Z: tn_nodeMode v1-4 CvvActive, o5+r6 Observer; as-run part A written
- B1 STARTED 01:40:52Z: --from 15 --to 16 (log s15-16.log, rc s15-16.rc). DO NOT RE-RUN step 15 blindly; wait on rc.
- B1 DONE 01:42:46Z rc=0 (RPC-EDGE ok, POSTCHECK 64 ok / 0 FAIL / 0 not-decisive)
- B2 DONE 01:43:15Z: rpc-6 entered 01:41:43 NRestarts=0; node5 net_peerCount 0x1; as-run part B written
- C1 STARTED 01:43:53Z: --from 17 --to 19 (log s17-19.log, rc s17-19.rc). Wait on rc; do not re-run.
- C1 progress: step 17 done (228 s), step 18 done (476 s); step 19 txgen sub-step 5 (VM musl build, 15-30 min) running since ~01:57Z
- C1 DONE 02:17:13Z rc=0 (step 19 done 1290 s)
- C2 DONE 02:18:45Z: admin 401 x5, tn-contracts clean, head 304->383 in 15 s, six node heads 503..594 rising; as-run part C written; token watcher stopped
next: none (hand back). Do not re-run any step.
