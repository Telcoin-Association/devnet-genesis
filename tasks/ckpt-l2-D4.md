status: DONE (A, B, C, D all passed; no stop condition, no kill switch; as-run written 02:44Z)

# D4 checkpoint (step 20, committee P2P allowlist)

Outputs: tasks/l2/w3/d4/  (as-run.md = the record; helpers probe.sh, s8reads.sh, waitrc.sh)

- A baseline: DONE 02:27Z. --status rc=0 all off ("check: no result line (exit 1)" per host); fleet whole.
- B canary node1: DONE rc=0 (02:27:54Z-02:28:49Z). `P2P_COMMITTEE validator-1-devnet on epoch=2 v4=5 v6=0 keys=4
  check=ok mode=CvvActive head=2682`. Set = v1..v4 + rpc-6. Health 3 reads PASS.
- C validators 2-4: DONE rc=0 (02:31:16Z, `## step 20 done (190 s)`, logs/20261118_023116-deploy/deploy.log).
  --status rc=0 all on check=ok; fleet whole at 02:35Z/02:36Z.
- D node5: DONE rc=0 mode=Observer (02:37:01Z-02:38:47Z). `P2P_COMMITTEE observer-5-devnet on epoch=2 v4=5 v6=0
  keys=5 check=ok mode=Observer head=5667`. Peers >=1, head rising; burst lag (130/32 blocks) on 2 of 5 reads, level next read.

End state: allowlist ON on validator-1..4 and observer-5; rpc-6 untouched (off); gateway-4 n/a.
Nothing left to run for D4.
