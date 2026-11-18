status: DONE (A, B, C, D complete; one gateway restart 04:06:21Z, one node restart 04:09:15Z on validator 2)
completed:
- A 04:06:01: v1-v4 CvvActive, peers 4 each, head rising (21465->21473 in 10s); v2 telcoin ActiveEnter 01:24:45, gateway ActiveEnter 01:17:02, NRestarts 0/0; nft md5 381d93a7eab2d25e53ac5ba0016efd53; check rc=0; ready=200
- B 04:06:21: gateway restarted once (returned 04:06:22, rc=0); /ready 000 at :22, 503 :23-:27, 200 from :28 (~6 s non-200); node2 /ready/any 200 ready=true; eth_chainId 0x7e1d; rpc-6 journal demot=0 (2 min); telcoin ActiveEnter unchanged 01:24:45
- C STARTED 2026-11-18T04:09:13Z (recheck: v1/v3/v4 CvvActive, pub 21658->21662). DO NOT RESTART AGAIN; observe only.
- C observed: v2 restart returned 04:09:18 rc=0; RPC not answering 04:09:24; CvvActive at 04:09:36, 04:09:50, 04:10:09 (3 consecutive, head level); v1/v3/v4 CvvActive at 04:09:24 and 04:10:09. Next: post-check at ~04:11:15, then D.
- C post-check 04:11:15: unit active since 04:09:18 (NRestarts 0); nft table inet tn_p2p_allow loaded; md5 fcb98ca0... (differs from A, checking counters); check rc=0; timer active; ready 200; log: subscriber starting node_mode=CvvActive 04:09:22.84; rpc-6 demot=0. Next: D.
- D 04:11:55-04:12:25: v1-v4 CvvActive peers 4, heads level; observer-5 Observer peers 1; rpc-6 Observer peers 5; pub 21813->21832; p2p-committee --status rc=0 all on/ok.
- record: tasks/l2/w3/vb/as-run.md written.
