status: done
updated: 2026-11-17T21:15Z

# RH5 checkpoint (local rehearsal: tx via the RPC node -> worker gateways -> block)
S=/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/RH5 (kept). Harness copied from RH3 (renamed l2rh5, subnet 172.30.105.0/24, nodeN=.1N, gwK=.2K).
Rebuild from scratch (about 3 min):
  docker rm -f $(docker ps -aq --filter name=l2rh5-) ; docker network rm l2rh5-net ; rm -rf $S/data $S/ws/genesis $S/ws/parameters.yaml
  bash $S/bin/setup.sh            # keys (validators advertise http://172.30.105.2K:8655/), funded throwaway key $S/secret/wallet.json
  (cd $S && CONFIG_FILE=$S/config-rh5.sh bash /home/drtnarg/coding/telcoin/dg-l2/devnet-genesis-build.sh)
  bash $S/bin/step4.sh            # admission maps + network-config per node (TND renderer)
  bash $S/bin/startall.sh         # node1-4, gw1-4 (gw.sh: gw_validate_inputs + gw_render_args), watchers, node6 (127.0.0.1:18645)
Tools: status.sh NAMES, rpc.sh NAME METHOD [PARAMS], snap.sh LABEL (node6 forward metrics + gateway counters),
  sign.sh COUNT NAME (presign), blast.sh NAME URL [THREADS] (post + wait receipts), peek.sh K PORT PATH, nmet.sh NAME.
  $S/fees holds MF/TIP (written after Q3).
## Completed sections
- harness written
- 21:08Z Q1 START done: node1-4 started 21:06:23, gw1-4 21:06:24 (gw_validate_inputs path), node6 21:06:31; nodes accepting 21:06:27, gw /ready 200 21:06:35 (all 4); 21:08:15 4x CvvActive + node6 Observer, block 1 everywhere
- 21:09Z Q2 done: node6 tn_worker_submit_expected_members 4 usable 4, no 'no committee validator has advertised' warning; Q3 done: cast send 21:08:40.325 -> receipt status 1 in 1.29s, tx 0x7ee65139…, block 2, miner node1; node6 'batch built num_txs=1' 21:08:40.390; queued_total 1; gw1 routed worker forwarded 1 (others 0). fees file MF=100 TIP=1
- 21:09Z Q4 done: 20 presigned (nonces 1..20) posted to node6 in 0.01s, http 200 x20, 20/20 status 1 within 1.01s, all in block 3 miner node1; queued_total 1->21; gw1 worker forwarded 1->21, gw2-4 0; no 429, no demot/unreachable lines
- 21:09Z Q5 done: via gw1 (host->172.30.105.21:8655): eth_getBalance 200 answered, tn_nodeMode 'Observer' (node1 direct: CvvActive), eth_chainId 0x7e1d; gw1 query forwarded 3; raw tx nonce 21 posted to gw1 directly -> status 1 in ~1s, block 4 miner node1, node6 queued unchanged 21; gw1 worker 22
- 21:12Z Q6 part 1 done: stopped gw1 (owner's gateway; gw2 would test nothing: every forward of this sender goes to node1 first) 21:09:51.9; 5 tx -> 5/5 status 1 in 6.02s, block 5 miner node4; 7 singles every 10s all status 1 (miners node2/node3); node6 warn 'demoting unreachable validator RPC endpoints from forward admission demoted=1 cooldown_secs=30' at 21:09:57.159, 21:10:23.763, 21:11:01.628 (no URL in the line); demoted_total 3, usable_members 4->3; gw2 4, gw3 3, gw4 5 worker forwards; epoch 2 began 21:10:12 (block 8, 0 tx); 2nd retry of gw1 only 21.6s after 1st demotion (cooldown lost at epoch change? inferred)
- 21:12Z Q6 done: docker start gw1 21:12:06.4; 5 tx sent before gw1 ready (harness loop bug) -> gw1 answered 503 no_upstream_ready, node6 demoted it (4th line 21:12:06.79), txs went to node4, status 1 in 1.01s; gw1 /ready 200 21:12:18.16; after cooldown 5 tx at 21:12:40 -> gw1 worker forwarded 5, block 16 miner node1, usable_members 4
- 21:13Z Q7 done: 400 presigned (nonces 44..443) posted to node6 with 8 threads in 0.07s, http 200 x400; 400/400 status 1, last receipt 4.65s; miners node1 210, node4 190; gw1 rate_limited 1 -> node6 demotion (demoted_total 5), requeued 61, queued_total 504; routed worker gw1 +210, gw4 +210, gw2 +41
- 21:15Z Q8 done 21:13:39: all l2rh5- containers + l2rh5-net removed (empty listings), 18645 gone, logs in $S/logs/final-*.log; report tasks/l2/rh5-report.md written
